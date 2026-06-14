"""GhLabelTaskSource — label_rules task source.

Fetches the oldest eligible open GitHub issue/PR carrying a configured label,
excluding items with ``ai-failed`` and the done label.  All subprocess calls
use list-form args with shell=False (ARCHITECTURE line 900; enforced by bandit B602).

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime
from typing import Any

from labro.config.schema import (
    GhLabelSource as GhLabelSourceConfig,
)
from labro.config.schema import (
    LabelRule,
    PermittedAction,
    PersonaConfig,
    ProjectConfig,
)
from labro.models import AgentConfig, Task, make_task_id
from labro.task_sources.base import TaskSource

logger = logging.getLogger(__name__)

_AI_FAILED_LABEL = "ai-failed"
_AI_HANDOVER_LABEL = "ai-handover"


def _run_gh_api(url: str) -> Any:
    """Run ``gh api --paginate <url>`` (list-form, shell=False) and return parsed JSON.

    The URL must include any query parameters inline (e.g.
    ``repos/owner/repo/issues?state=open&labels=ai-dev``) so that ``gh api``
    treats the request as a GET rather than inferring POST from ``-f`` flags.

    Raises:
        subprocess.CalledProcessError: if gh exits non-zero.
        json.JSONDecodeError: if stdout is not valid JSON.
    """
    result = subprocess.run(  # — list-form args, shell=False
        ["gh", "api", "--paginate", url],
        capture_output=True,
        text=True,
        check=True,
        shell=False,
    )
    return json.loads(result.stdout)


def _label_names(item: dict[str, Any]) -> set[str]:
    """Return the set of label name strings on a GitHub API item."""
    return {lbl["name"] for lbl in item.get("labels", [])}


def _item_type(item: dict[str, Any]) -> str:
    """Return ``"pr"`` if *item* is a pull request, else ``"issue"``."""
    return "pr" if "pull_request" in item else "issue"


def _resolve_permitted_actions(
    rule: LabelRule,
    source: GhLabelSourceConfig,
    project: ProjectConfig,
) -> list[PermittedAction]:
    """Resolve permitted_actions using the override chain.

    Resolution order (most specific wins): rule → source → project.
    Returns an empty list only when no level configures permitted_actions;
    config validation should surface this condition at load time.
    """
    if rule.permitted_actions is not None:
        return rule.permitted_actions
    if source.permitted_actions is not None:
        return source.permitted_actions
    if project.permitted_actions is not None:
        return project.permitted_actions
    return []


def _resolve_model_slug(
    rule: LabelRule,
    source: GhLabelSourceConfig,
    project: ProjectConfig,
    defaults_model: list[str],
) -> list[str]:
    """Resolve model slug list: rule → source → project → defaults."""
    if rule.model is not None:
        return rule.model
    if source.model is not None:
        return source.model
    if project.model is not None:
        return project.model
    return defaults_model


def _fetch_comments_section(repo: str, number: int, max_comments: int) -> str:
    """Fetch the last *max_comments* comments on *repo* issue/PR *number*.

    Returns a formatted string ready to append to the task description, or an
    empty string if there are no comments.  Failures are swallowed so a comment-
    fetch error never blocks task selection.
    """
    try:
        comments: list[dict[str, Any]] = _run_gh_api(
            f"repos/{repo}/issues/{number}/comments?per_page=100"
        )
    except Exception:
        return ""

    if not comments:
        return ""

    total = len(comments)
    tail = comments[-max_comments:]
    showing = len(tail)

    if total > showing:
        header = (
            f"\n\n**Comments (showing last {showing} of {total}):**"
            f"\n*{total - showing} earlier comment(s) not shown."
            f" Run `gh api repos/{repo}/issues/{number}/comments`"
            f" to fetch the full thread if earlier context seems relevant.*"
        )
    else:
        header = f"\n\n**Comments ({total}):**"

    parts = [header]
    for c in tail:
        author: str = c.get("user", {}).get("login", "unknown")
        created: str = c.get("created_at", "")[:10]  # YYYY-MM-DD
        body: str = (c.get("body") or "").strip()
        parts.append(f"\n**@{author}** ({created}):\n{body}")

    return "\n".join(parts)


class GhLabelTaskSource(TaskSource):
    """Task source that monitors GitHub items via the ``gh`` CLI.

    Selects the oldest open item carrying a configured label (``label_rules``).
    Candidates from all rules are merged and sorted by ``created_at``; the
    globally oldest eligible item is returned.
    """

    def __init__(
        self,
        source_config: GhLabelSourceConfig,
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
        """Return the oldest eligible labelled item across all label_rules, or None."""
        candidates: list[tuple[datetime, dict[str, Any], LabelRule]] = []

        for rule in self._cfg.label_rules:
            items = _run_gh_api(
                f"repos/{project.repo}/issues?state=open&labels={rule.label}&per_page=100"
            )
            for item in items:
                labels = _label_names(item)
                if _AI_FAILED_LABEL in labels:
                    continue
                if _AI_HANDOVER_LABEL in labels:
                    continue
                if rule.done_label in labels:
                    continue
                created_at = datetime.fromisoformat(item["created_at"].replace("Z", "+00:00"))
                candidates.append((created_at, item, rule))

        if not candidates:
            logger.debug("gh-label: no eligible candidates in %s", project.repo)
            return None

        # Pick oldest by created_at (stable: ties broken by insertion order)
        candidates.sort(key=lambda t: t[0])
        _ts, item, winning_rule = candidates[0]

        logger.info(
            "gh-label: picked %s #%d %r via label_rule label=%r (%d candidate%s)",
            _item_type(item),
            item["number"],
            item.get("title", ""),
            winning_rule.label,
            len(candidates),
            "s" if len(candidates) != 1 else "",
        )

        model = _resolve_model_slug(winning_rule, self._cfg, project, defaults_model)
        done_label = winning_rule.done_label
        permitted_actions = _resolve_permitted_actions(winning_rule, self._cfg, project)
        max_turns = project.max_turns if project.max_turns is not None else defaults_max_turns
        timeout_s = project.timeout_s if project.timeout_s is not None else defaults_timeout_s
        max_comments = (
            project.max_comments if project.max_comments is not None else defaults_max_comments
        )

        itype = _item_type(item)
        number: int = item["number"]
        url: str = item["html_url"]
        title: str = item.get("title", "")
        body: str = item.get("body") or ""
        description = f"#{number}: {title}\n\n{body}".strip()
        description += _fetch_comments_section(project.repo, number, max_comments)

        persona_prompt: str | None = None
        if winning_rule.persona is not None:
            p = self._personas.get(winning_rule.persona)
            if p is not None:
                persona_prompt = p.prompt

        task = Task(
            task_id=make_task_id(),
            source="gh-label",
            description=description,
            permitted_actions=permitted_actions,
            repo=project.repo,
            item_type=itype,
            item_number=number,
            item_url=url,
            source_label=winning_rule.label,
            done_label=done_label,
            grafana_rule_uid=None,
            persona_prompt=persona_prompt,
            source_description=winning_rule.description,
        )
        agent_cfg = AgentConfig.from_slug_list(
            model,
            max_turns=max_turns,
            timeout_s=timeout_s,
            permitted_actions=task.permitted_actions,
        )
        return task, agent_cfg
