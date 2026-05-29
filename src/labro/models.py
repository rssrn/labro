"""Task, AgentConfig, AgentResult, and ItemRef data models.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path

from labro.config.schema import PermittedAction


@dataclass
class Task:
    """A unit of work selected by the picker and consumed by the prompt builder.

    All config resolution (label_rule → source → project → defaults) happens
    inside the task source before returning — Task carries only resolved values.
    """

    task_id: str  # UUID v4, generated at selection time
    source: str  # "grafana-alerts" | "gh-label" | "proactive-improvement"
    description: str  # human-readable; inserted into prompt section 2
    permitted_actions: list[PermittedAction]  # effective set; inserted into prompt section 3

    # GitHub item reference
    repo: str  # "owner/repo" — always the project's configured repo
    item_type: str | None  # "issue" | "pr" — None for grafana-alerts / proactive-improvement
    item_number: int | None
    item_url: str | None

    # Label transitions — post_run.py only; None for sources with no pre-existing item
    source_label: str | None  # label to remove on success (gh-label label_rules only)
    done_label: str | None  # label to apply on success (gh-label only)
    grafana_rule_uid: str | None  # rule UID for grafana-alerts tasks

    # Original GitHub assignees (logins) at task-selection time — used by
    # assignee.py to restore after the run.
    assignees: list[str] = field(default_factory=list)

    # Optional persona prompt prepended to the role section of the agent prompt.
    persona_prompt: str | None = None


def make_task_id() -> str:
    """Generate a fresh UUID v4 task identifier."""
    return str(uuid.uuid4())


@dataclass
class ItemRef:
    """A reference to a GitHub item (issue or PR) created by the agent."""

    item_type: str  # "issue" | "pr"
    item_number: int


@dataclass
class AgentResult:
    """Structured outcome returned by an agent after a run.

    Token fields map directly to Claude API usage fields.
    ``partial`` is a valid agent outcome but is stored as ``failure``
    in the SQLite runs table (ARCHITECTURE line 263); the distinction
    is preserved only in ``summary`` / ``failure_reason``.
    """

    outcome: str  # "success" | "failure" | "partial"
    summary: str
    actions_taken: list[str] = field(default_factory=list)
    items_created: list[ItemRef] = field(default_factory=list)
    failure_reason: str | None = None
    is_error: bool = False
    num_turns: int = 0
    total_cost_usd: float = 0.0
    duration_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass
class AgentConfig:
    """Resolved agent invocation parameters produced by the picker alongside Task."""

    agent: str  # "claude-code" (only supported value in v1)
    model: str  # e.g. "claude-sonnet-4-6" — passed through to CLI as --model
    max_turns: int  # passed to claude as --max-turns
    timeout_s: int  # subprocess wall-clock timeout
    effort: str | None = None  # e.g. "high" — passed to CLI as --effort if set
    cwd: Path | None = None  # working directory for the agent subprocess (ARCHITECTURE line 630)
    permitted_actions: list[PermittedAction] = field(default_factory=list)  # drives --allowedTools
