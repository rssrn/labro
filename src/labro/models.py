"""Task and AgentConfig data models.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from labro.config.schema import PermittedAction


@dataclass
class Task:
    """A unit of work selected by the picker and consumed by the prompt builder.

    All config resolution (label_rule → source → project → defaults) happens
    inside the task source before returning — Task carries only resolved values.
    """

    task_id: str  # UUID v4, generated at selection time
    source: str  # "grafana-alerts" | "gh-delegated" | "proactive-improvement"
    description: str  # human-readable; inserted into prompt section 2
    permitted_actions: list[PermittedAction]  # effective set; inserted into prompt section 3

    # GitHub item reference
    repo: str  # "owner/repo" — always the project's configured repo
    item_type: str | None  # "issue" | "pr" — None for grafana-alerts / proactive-improvement
    item_number: int | None
    item_url: str | None

    # Label transitions — post_run.py only; None for sources with no pre-existing item
    source_label: str | None  # label to remove on success (gh-delegated label_rules only)
    done_label: str | None  # label to apply on success (gh-delegated only)
    grafana_rule_uid: str | None  # rule UID for grafana-alerts tasks


def make_task_id() -> str:
    """Generate a fresh UUID v4 task identifier."""
    return str(uuid.uuid4())


@dataclass
class AgentConfig:
    """Resolved agent invocation parameters produced by the picker alongside Task."""

    agent: str  # "claude-code" (only supported value in v1)
    model: str  # e.g. "claude-sonnet-4-6" — passed through to CLI as --model
    max_turns: int  # passed to claude as --max-turns
    timeout_s: int  # subprocess wall-clock timeout
