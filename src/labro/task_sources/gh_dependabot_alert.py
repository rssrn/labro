"""DependabotAlertTaskSource — raise issues for unfixed Dependabot alerts.

Fetches open Dependabot security alerts via the ``gh`` CLI and raises a GitHub
issue for the first alert that has no fix PR merged (``fixed_at`` is null) and
no existing issue tracking it.  A dedicated label (``ai-dependabot-alert`` by
default) is applied to each created issue so the source can detect duplicates
across runs.

All subprocess calls use list-form args with shell=False (enforced by bandit B602).

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from datetime import UTC, datetime, timedelta
from typing import Any

from labro.config.schema import (
    DependabotAlertSource as DependabotAlertSourceConfig,
)
from labro.config.schema import (
    PermittedAction,
    PersonaConfig,
    ProjectConfig,
)
from labro.models import AgentConfig, Task, make_task_id
from labro.task_sources.base import TaskSource

logger = logging.getLogger(__name__)

_DEFAULT_PERMITTED_ACTIONS: list[PermittedAction] = [
    PermittedAction.COMMENT_ON_ISSUE,
    PermittedAction.OPEN_PR,
]

_ISSUE_URL_RE = re.compile(r"/issues/(\d+)$")


def _run_gh_api(url: str) -> Any:
    """Run ``gh api --paginate <url>`` (list-form, shell=False) and return parsed JSON."""
    result = subprocess.run(
        ["gh", "api", "--paginate", url],
        capture_output=True,
        text=True,
        check=True,
        shell=False,
    )
    return json.loads(result.stdout)


def _ensure_label(repo: str, label: str) -> None:
    """Create *label* in *repo* if it does not already exist (no-op if it does)."""
    subprocess.run(
        ["gh", "label", "create", label, "--repo", repo, "--force"],
        capture_output=True,
        shell=False,
    )


def _fetch_open_alerts(repo: str) -> list[dict[str, Any]]:
    """Return all open Dependabot alerts for *repo* with no fix merged.

    Each alert dict includes ``dependency``, ``security_advisory``, and
    ``created_at`` fields.  Alerts with ``fixed_at`` set (fix already merged)
    are excluded.  Failures (alerts disabled, missing token scope, 404) are
    swallowed and yield an empty list.
    """
    try:
        alerts: list[dict[str, Any]] = _run_gh_api(
            f"repos/{repo}/dependabot/alerts?state=open&per_page=100"
        )
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        logger.warning(
            "gh-dependabot-alert: failed to fetch alerts for %s (exit %d)%s",
            repo,
            exc.returncode,
            f": {stderr}" if stderr else "",
        )
        return []
    except Exception:
        logger.warning("gh-dependabot-alert: failed to fetch alerts for %s", repo, exc_info=True)
        return []

    # Only alerts with no fix merged — Dependabot couldn't auto-fix or fix PR
    # is still open.
    unfixed = [a for a in alerts if a.get("fixed_at") is None]
    return unfixed


def _has_tracking_issue(alert: dict[str, Any], existing_issues: list[dict[str, Any]]) -> bool:
    """True if any existing issue already tracks *alert*, matched on GHSA ID.

    Returns False when the alert has no GHSA ID so that unidentified alerts
    are always actioned rather than silently skipped.
    """
    advisory = alert.get("security_advisory") or {}
    ghsa_id = (advisory.get("ghsa_id") or "").lower()
    if not ghsa_id:
        return False
    return any(ghsa_id in (issue.get("body") or "").lower() for issue in existing_issues)


def _is_active_issue(issue: dict[str, Any], cutoff: datetime) -> bool:
    """True if *issue* is open, or was closed on or after *cutoff*.

    Issues with a missing or malformed ``closed_at`` are treated as inactive
    so they never permanently block re-creation.
    """
    if issue.get("state") == "open":
        return True
    if issue.get("state") == "closed":
        closed_raw: str | None = issue.get("closed_at")
        if not closed_raw:
            return False
        try:
            closed = datetime.fromisoformat(closed_raw.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return False
        return closed >= cutoff
    return False


def _severity_sort_key(alert: dict[str, Any]) -> int:
    """Return a sort key: critical=0, high=1, medium=2, low=3, unknown=4."""
    advisory = alert.get("security_advisory") or {}
    sev = (advisory.get("severity") or "unknown").lower()
    return {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(sev, 4)


def _build_issue_body(alert: dict[str, Any]) -> str:
    """Return a GitHub issue body describing *alert*."""
    dep = alert.get("dependency") or {}
    pkg = (dep.get("package") or {}).get("name", "unknown")
    manifest = dep.get("manifest_path", "unknown")
    requirements = dep.get("requirements", "")
    advisory = alert.get("security_advisory") or {}
    ghsa_id = advisory.get("ghsa_id", "")
    cve_id = advisory.get("cve_id", "")
    summary = advisory.get("summary", "")
    description = advisory.get("description", "")
    severity = advisory.get("severity", "unknown")
    vuln = alert.get("security_vulnerability") or {}
    vulnerable_range = vuln.get("vulnerable_version_range", "")
    patched_versions = vuln.get("patched_versions", "")

    lines = [
        "<!-- Labro Dependabot alert — do not edit this header -->",
        f"**Package:** `{pkg}`",
        f"**Manifest:** `{manifest}`",
        f"**Severity:** {severity}",
    ]
    if ghsa_id:
        lines.append(f"**GHSA:** `{ghsa_id}`")
    if cve_id:
        lines.append(f"**CVE:** `{cve_id}`")
    if summary:
        lines.append(f"**Summary:** {summary}")
    if vulnerable_range:
        lines.append(f"**Vulnerable range:** {vulnerable_range}")
    if patched_versions:
        lines.append(f"**Patched versions:** {patched_versions}")
    if requirements:
        lines.append(f"**Current requirement:** {requirements}")
    lines += [
        "",
        "---",
        "",
    ]
    if description:
        lines.append(description)
        lines.append("")
    lines.extend(
        [
            "Dependabot was unable to create an automatic fix PR for this alert"
            " (e.g. due to incompatible version constraints).",
            "",
            "A manual fix is required — update the dependency to a patched version"
            " or resolve the conflict.",
        ]
    )

    return "\n".join(lines)


def _create_issue(repo: str, title: str, body: str, label: str) -> tuple[int, str]:
    """Create a GitHub issue with *label* and return ``(number, url)``."""
    _ensure_label(repo, label)
    result = subprocess.run(
        [
            "gh",
            "issue",
            "create",
            "--repo",
            repo,
            "--title",
            title,
            "--body",
            body,
            "--label",
            label,
        ],
        capture_output=True,
        text=True,
        check=True,
        shell=False,
    )
    url = result.stdout.strip()
    m = _ISSUE_URL_RE.search(url)
    if not m:
        raise ValueError(f"could not parse issue number from gh output: {url!r}")
    return int(m.group(1)), url


class DependabotAlertTaskSource(TaskSource):
    """Task source that creates issues for unfixed Dependabot security alerts."""

    def __init__(
        self,
        source_config: DependabotAlertSourceConfig,
        personas: dict[str, PersonaConfig] | None = None,
    ) -> None:
        self._cfg = source_config
        self._personas: dict[str, PersonaConfig] = personas or {}

    def fetch_task(
        self,
        project: ProjectConfig,
        defaults_model: list[str],
        defaults_max_turns: int,
        defaults_timeout_s: int,
        defaults_max_comments: int,
    ) -> tuple[Task, AgentConfig] | None:
        repo = project.repo
        label = self._cfg.alert_label

        # ── Fetch open alerts ──────────────────────────────────────────────────
        alerts = _fetch_open_alerts(repo)
        if not alerts:
            logger.debug("gh-dependabot-alert: no open unfixed alerts in %s", repo)
            return None

        # ── Fetch existing tracking issues for dedup ───────────────────────────
        cutoff = datetime.now(UTC) - timedelta(days=10)
        try:
            all_existing: list[dict[str, Any]] = _run_gh_api(
                f"repos/{repo}/issues?state=all&labels={label}&per_page=100"
            )
        except (subprocess.CalledProcessError, ValueError) as exc:
            logger.warning(
                "gh-dependabot-alert: failed to fetch existing issues for %s: %s",
                repo,
                exc,
            )
            return None

        # Only open issues and recently-closed issues block re-creation.
        existing = [iss for iss in all_existing if _is_active_issue(iss, cutoff)]

        # ── Find first unaddressed alert (highest severity first) ──────────────
        alerts.sort(key=_severity_sort_key)
        target: dict[str, Any] | None = None
        for alert in alerts:
            if not _has_tracking_issue(alert, existing):
                target = alert
                break

        if target is None:
            logger.debug(
                "gh-dependabot-alert: all open alerts already have tracking issues in %s", repo
            )
            return None

        # ── Resolve config ─────────────────────────────────────────────────────
        model_slugs: list[str] = self._cfg.model or project.model or defaults_model
        permitted_actions: list[PermittedAction] = (
            self._cfg.permitted_actions or project.permitted_actions or _DEFAULT_PERMITTED_ACTIONS
        )
        persona_prompt: str | None = None
        if self._cfg.persona and self._cfg.persona in self._personas:
            persona_prompt = self._personas[self._cfg.persona].prompt

        max_turns = defaults_max_turns
        timeout_s = defaults_timeout_s

        # ── Build agent config ─────────────────────────────────────────────────
        agent_cfg = AgentConfig.from_slug_list(
            model_slugs,
            max_turns=max_turns,
            timeout_s=timeout_s,
            permitted_actions=permitted_actions,
        )

        # ── Create GitHub issue ────────────────────────────────────────────────
        dep = target.get("dependency") or {}
        pkg = (dep.get("package") or {}).get("name", "unknown")
        advisory = target.get("security_advisory") or {}
        ghsa_id = advisory.get("ghsa_id", "")
        severity = advisory.get("severity", "unknown")
        title = f"Dependabot alert: {pkg}"
        if ghsa_id:
            title += f" ({ghsa_id})"
        title += f" [{severity}]"

        body = _build_issue_body(target)

        try:
            item_number, item_url = _create_issue(repo, title, body, label)
        except (subprocess.CalledProcessError, ValueError) as exc:
            logger.warning("gh-dependabot-alert: failed to create issue in %s: %s", repo, exc)
            return None

        logger.info(
            "gh-dependabot-alert: created issue #%d for %s (%s, %s)",
            item_number,
            pkg,
            severity,
            ghsa_id or "no GHSA",
        )

        # ── Build task description ─────────────────────────────────────────────
        description = (
            f"Dependabot alert for **{pkg}** (severity: {severity}).\n\n"
            f"See issue #{item_number} for full alert details."
        )

        task = Task(
            task_id=make_task_id(),
            source="gh-dependabot-alert",
            description=description,
            permitted_actions=permitted_actions,
            repo=repo,
            item_type="issue",
            item_number=item_number,
            item_url=item_url,
            source_label=None,
            done_label=None,
            grafana_rule_uid=None,
            persona_prompt=persona_prompt,
            source_description=f"🛡️ Dependabot alert: {pkg}",
        )

        return task, agent_cfg
