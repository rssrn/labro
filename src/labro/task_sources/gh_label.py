"""GhLabelTaskSource — label_rules and actor_rules task source (M2 scope).

Fetches the oldest eligible open GitHub issue/PR carrying a configured label
(label_rules) or created by a configured GitHub actor (actor_rules), excluding
items with ``ai-failed`` and the done label.  All subprocess calls use
list-form args with shell=False (ARCHITECTURE line 900; enforced by bandit B602).

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime
from typing import Any

from labro.config.schema import (
    ActorRule,
    LabelRule,
    PermittedAction,
    ProjectConfig,
)
from labro.config.schema import (
    GhLabelSource as GhLabelSourceConfig,
)
from labro.models import AgentConfig, Task, make_task_id
from labro.task_sources.base import TaskSource

logger = logging.getLogger(__name__)

_AI_FAILED_LABEL = "ai-failed"

# Type alias for any rule supported by GhLabelTaskSource.
_AnyRule = LabelRule | ActorRule


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
    rule: _AnyRule,
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


def _resolve_model(
    source: GhLabelSourceConfig,
    project: ProjectConfig,
    defaults_model: str,
) -> str:
    """Resolve model for label_rules using the override chain: source → project → defaults."""
    if source.model is not None:
        return source.model
    if project.model is not None:
        return project.model
    return defaults_model


def _resolve_model_for_actor(
    rule: ActorRule,
    source: GhLabelSourceConfig,
    project: ProjectConfig,
    defaults_model: str,
) -> str:
    """Resolve model for an actor_rule: rule → source → project → defaults."""
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
        header = f"\n\n**Comments (showing last {showing} of {total}):**"
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

    Supports both ``label_rules`` (items carrying a specific label) and
    ``actor_rules`` (items created by a specific GitHub login).  Candidates
    from all rules are merged into a single pool sorted by ``created_at``
    (oldest first); the globally oldest eligible item is selected.
    """

    def __init__(self, source_config: GhLabelSourceConfig) -> None:
        self._cfg = source_config

    def fetch_task(
        self,
        project: ProjectConfig,
        defaults_model: str,
        defaults_max_turns: int,
        defaults_timeout_s: int,
        defaults_max_comments: int,
    ) -> tuple[Task, AgentConfig] | None:
        """Return the oldest eligible item across all label_rules and actor_rules, or None."""
        candidates: list[tuple[datetime, dict[str, Any], _AnyRule]] = []

        # ── label_rules: fetch items matching the label via GH API query ───────
        for rule in self._cfg.label_rules:
            items = _run_gh_api(
                f"repos/{project.repo}/issues?state=open&labels={rule.label}&per_page=100"
            )
            for item in items:
                labels = _label_names(item)
                if _AI_FAILED_LABEL in labels:
                    continue
                if rule.done_label in labels:
                    continue
                created_at = datetime.fromisoformat(item["created_at"].replace("Z", "+00:00"))
                candidates.append((created_at, item, rule))

        # ── actor_rules: fetch all open items once, filter client-side ─────────
        # Cache the all-open fetch so N actor_rules only incur one API round-trip.
        _all_open_items: list[dict[str, Any]] | None = None

        for actor_rule in self._cfg.actor_rules:
            if _all_open_items is None:
                _all_open_items = _run_gh_api(
                    f"repos/{project.repo}/issues?state=open&per_page=100"
                )
            for item in _all_open_items:
                actor_login: str = (item.get("user") or {}).get("login", "")
                if actor_login != actor_rule.actor:
                    continue
                labels = _label_names(item)
                if _AI_FAILED_LABEL in labels:
                    continue
                if actor_rule.done_label in labels:
                    continue
                created_at = datetime.fromisoformat(item["created_at"].replace("Z", "+00:00"))
                candidates.append((created_at, item, actor_rule))

        if not candidates:
            logger.debug("gh-label: no eligible candidates in %s", project.repo)
            return None

        # Pick oldest by created_at (stable: ties broken by insertion order)
        candidates.sort(key=lambda t: t[0])
        _ts, item, winning_rule = candidates[0]

        _itype_pre = _item_type(item)
        _number_pre: int = item["number"]
        _title_pre: str = item.get("title", "")
        if isinstance(winning_rule, ActorRule):
            _rule_desc = f"actor_rule actor={winning_rule.actor!r}"
        else:
            _rule_desc = f"label_rule label={winning_rule.label!r}"
        logger.info(
            "gh-label: picked %s #%d %r via %s (%d candidate%s)",
            _itype_pre,
            _number_pre,
            _title_pre,
            _rule_desc,
            len(candidates),
            "s" if len(candidates) != 1 else "",
        )

        # Rule-specific field resolution
        source_label: str | None
        model: str
        if isinstance(winning_rule, ActorRule):
            source_label = None
            model = _resolve_model_for_actor(winning_rule, self._cfg, project, defaults_model)
        else:
            source_label = winning_rule.label
            model = _resolve_model(self._cfg, project, defaults_model)

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

        task = Task(
            task_id=make_task_id(),
            source="gh-label",
            description=description,
            permitted_actions=permitted_actions,
            repo=project.repo,
            item_type=itype,
            item_number=number,
            item_url=url,
            source_label=source_label,
            done_label=done_label,
            grafana_rule_uid=None,
        )
        agent_cfg = AgentConfig(
            agent="claude-code",
            model=model,
            max_turns=max_turns,
            timeout_s=timeout_s,
            permitted_actions=task.permitted_actions,
        )
        return task, agent_cfg
