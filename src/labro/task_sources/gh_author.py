"""GhAuthorTaskSource — author_rules task source.

Fetches the oldest eligible open GitHub issue/PR created by a configured GitHub
login (author_rules), excluding items with ``ai-failed`` and the done label.
All subprocess calls use list-form args with shell=False (enforced by bandit B602).

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import datetime
from typing import Any

from labro.config.schema import (
    AuthorRule,
    PermittedAction,
    PersonaConfig,
    ProjectConfig,
)
from labro.config.schema import (
    GhAuthorSource as GhAuthorSourceConfig,
)
from labro.models import AgentConfig, Task, make_task_id
from labro.task_sources.base import TaskSource

logger = logging.getLogger(__name__)

_AI_FAILED_LABEL = "ai-failed"
_AI_HANDOVER_LABEL = "ai-handover"


def _run_gh_api(url: str) -> Any:
    """Run ``gh api --paginate <url>`` (list-form, shell=False) and return parsed JSON."""
    result = subprocess.run(  # — list-form args, shell=False
        ["gh", "api", "--paginate", url],
        capture_output=True,
        text=True,
        check=True,
        shell=False,
    )
    return json.loads(result.stdout)


def _label_names(item: dict[str, Any]) -> set[str]:
    return {lbl["name"] for lbl in item.get("labels", [])}


def _item_type(item: dict[str, Any]) -> str:
    return "pr" if "pull_request" in item else "issue"


def _resolve_permitted_actions(
    rule: AuthorRule,
    source: GhAuthorSourceConfig,
    project: ProjectConfig,
) -> list[PermittedAction]:
    """Resolve permitted_actions: rule → source → project."""
    if rule.permitted_actions is not None:
        return rule.permitted_actions
    if source.permitted_actions is not None:
        return source.permitted_actions
    if project.permitted_actions is not None:
        return project.permitted_actions
    return []


def _resolve_model_slug(
    rule: AuthorRule,
    source: GhAuthorSourceConfig,
    project: ProjectConfig,
    defaults_model: str,
) -> str:
    """Resolve model slug: rule → source → project → defaults."""
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
        created: str = c.get("created_at", "")[:10]
        body: str = (c.get("body") or "").strip()
        parts.append(f"\n**@{author}** ({created}):\n{body}")

    return "\n".join(parts)


class GhAuthorTaskSource(TaskSource):
    """Task source that monitors GitHub items opened by configured authors.

    Fetches all open issues/PRs, filters by author login (``author_rules``),
    and returns the oldest eligible item.
    """

    def __init__(
        self,
        source_config: GhAuthorSourceConfig,
        personas: dict[str, PersonaConfig] | None = None,
    ) -> None:
        self._cfg = source_config
        self._personas: dict[str, PersonaConfig] = personas or {}

    def fetch_task(
        self,
        project: ProjectConfig,
        defaults_model: str,
        defaults_max_turns: int,
        defaults_timeout_s: int,
        defaults_max_comments: int,
    ) -> tuple[Task, AgentConfig] | None:
        """Return the oldest eligible item across all author_rules, or None."""
        candidates: list[tuple[datetime, dict[str, Any], AuthorRule]] = []

        # Fetch all open items once; filter per-rule client-side.
        all_open: list[dict[str, Any]] | None = None

        for rule in self._cfg.author_rules:
            if all_open is None:
                all_open = _run_gh_api(f"repos/{project.repo}/issues?state=open&per_page=100")
            for item in all_open:
                author_login: str = (item.get("user") or {}).get("login", "")
                if author_login != rule.actor:
                    continue
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
            logger.debug("gh-author: no eligible candidates in %s", project.repo)
            return None

        candidates.sort(key=lambda t: t[0])
        _ts, item, winning_rule = candidates[0]

        logger.info(
            "gh-author: picked %s #%d %r via author_rule actor=%r (%d candidate%s)",
            _item_type(item),
            item["number"],
            item.get("title", ""),
            winning_rule.actor,
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
        assignees: list[str] = [a["login"] for a in item.get("assignees", [])]
        description = f"#{number}: {title}\n\n{body}".strip()
        description += _fetch_comments_section(project.repo, number, max_comments)

        persona_prompt: str | None = None
        if winning_rule.persona is not None:
            p = self._personas.get(winning_rule.persona)
            if p is not None:
                persona_prompt = p.prompt

        task = Task(
            task_id=make_task_id(),
            source="gh-author",
            description=description,
            permitted_actions=permitted_actions,
            repo=project.repo,
            item_type=itype,
            item_number=number,
            item_url=url,
            source_label=None,
            done_label=done_label,
            grafana_rule_uid=None,
            assignees=assignees,
            persona_prompt=persona_prompt,
        )
        agent_cfg = AgentConfig.from_slug(
            model,
            max_turns=max_turns,
            timeout_s=timeout_s,
            permitted_actions=task.permitted_actions,
        )
        return task, agent_cfg
