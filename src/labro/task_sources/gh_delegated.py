"""GhDelegatedTaskSource — label_rules task source (M1 scope).

Fetches the oldest eligible open GitHub issue/PR carrying a configured label
and NOT ``ai-failed`` and NOT the done label.  All subprocess calls use
list-form args with shell=False (ARCHITECTURE line 900; enforced by bandit B602).

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from typing import Any

from labro.config.schema import (
    GhDelegatedSource as GhDelegatedSourceConfig,
)
from labro.config.schema import (
    LabelRule,
    PermittedAction,
    ProjectConfig,
)
from labro.models import AgentConfig, Task, make_task_id
from labro.task_sources.base import TaskSource

_AI_FAILED_LABEL = "ai-failed"


def _run_gh_api(args: list[str]) -> Any:
    """Run ``gh api`` with *args* (list-form, shell=False) and return parsed JSON.

    Raises:
        subprocess.CalledProcessError: if gh exits non-zero.
        json.JSONDecodeError: if stdout is not valid JSON.
    """
    result = subprocess.run(  # — list-form args, shell=False
        ["gh", "api", "--paginate", *args],
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
    source: GhDelegatedSourceConfig,
    project: ProjectConfig,
) -> list[PermittedAction]:
    """Resolve permitted_actions using the override chain.

    Resolution order (most specific wins): label_rule → source → project.
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
    source: GhDelegatedSourceConfig,
    project: ProjectConfig,
    defaults_model: str,
) -> str:
    """Resolve model using the override chain: source → project → defaults."""
    if source.model is not None:
        return source.model
    if project.model is not None:
        return project.model
    return defaults_model


class GhDelegatedTaskSource(TaskSource):
    """Task source that monitors GitHub items via the ``gh`` CLI.

    M1 scope: label_rules only.  actor_rules are M2.
    """

    def __init__(self, source_config: GhDelegatedSourceConfig) -> None:
        self._cfg = source_config

    def fetch_task(
        self,
        project: ProjectConfig,
        defaults_model: str,
        defaults_max_turns: int,
        defaults_timeout_s: int,
    ) -> tuple[Task, AgentConfig] | None:
        """Return the oldest eligible labelled item across all label_rules, or None."""
        candidates: list[tuple[datetime, dict[str, Any], LabelRule]] = []

        for rule in self._cfg.label_rules:
            items = _run_gh_api(
                [
                    "-f",
                    "state=open",
                    "-f",
                    f"labels={rule.label}",
                    "-f",
                    "per_page=100",
                    f"repos/{project.repo}/issues",
                ]
            )
            for item in items:
                labels = _label_names(item)
                if _AI_FAILED_LABEL in labels:
                    continue
                if rule.done_label in labels:
                    continue
                created_at = datetime.fromisoformat(item["created_at"].replace("Z", "+00:00"))
                candidates.append((created_at, item, rule))

        if not candidates:
            return None

        # Pick oldest by created_at (stable: ties broken by insertion order)
        candidates.sort(key=lambda t: t[0])
        _ts, item, rule = candidates[0]

        permitted_actions = _resolve_permitted_actions(rule, self._cfg, project)
        model = _resolve_model(self._cfg, project, defaults_model)
        max_turns = project.max_turns if project.max_turns is not None else defaults_max_turns
        timeout_s = project.timeout_s if project.timeout_s is not None else defaults_timeout_s

        itype = _item_type(item)
        number: int = item["number"]
        url: str = item["html_url"]
        title: str = item.get("title", "")
        body: str = item.get("body") or ""
        description = f"#{number}: {title}\n\n{body}".strip()

        task = Task(
            task_id=make_task_id(),
            source="gh-delegated",
            description=description,
            permitted_actions=permitted_actions,
            repo=project.repo,
            item_type=itype,
            item_number=number,
            item_url=url,
            source_label=rule.label,
            done_label=rule.done_label,
            grafana_rule_uid=None,
        )
        agent_cfg = AgentConfig(
            agent="claude-code",
            model=model,
            max_turns=max_turns,
            timeout_s=timeout_s,
        )
        return task, agent_cfg
