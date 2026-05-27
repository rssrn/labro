"""Pydantic models for labro.toml (full schema).

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator


class PermittedAction(str, Enum):
    """Actions a Labro agent is allowed to perform on GitHub."""

    COMMENT_ON_ISSUE = "comment_on_issue"
    COMMENT_ON_PR = "comment_on_pr"
    OPEN_PR = "open_pr"
    MERGE_PR = "merge_pr"
    PUSH_DEFAULT = "push_default"
    CLOSE_ISSUE = "close_issue"
    CREATE_ISSUE = "create_issue"


# ── Task source models ─────────────────────────────────────────────────────────


class LabelRule(BaseModel):
    """A single label-based eligibility rule within a gh-delegated source."""

    label: str
    done_label: str
    permitted_actions: list[PermittedAction] | None = None


class ActorRule(BaseModel):
    """An actor-based eligibility rule within a gh-delegated source."""

    actor: str
    done_label: str
    model: str | None = None
    permitted_actions: list[PermittedAction] | None = None


class GhDelegatedSource(BaseModel):
    """Task source: gh-delegated (label_rules and/or actor_rules)."""

    type: Literal["gh-delegated"]
    label_rules: list[LabelRule] = Field(default_factory=list)
    actor_rules: list[ActorRule] = Field(default_factory=list)
    permitted_actions: list[PermittedAction] | None = None
    model: str | None = None

    @model_validator(mode="after")
    def require_at_least_one_rule(self) -> GhDelegatedSource:
        """gh-delegated with no rules is a hard config error."""
        if not self.label_rules and not self.actor_rules:
            raise ValueError(
                "gh-delegated source must define at least one label_rule or actor_rule"
            )
        return self


class GrafanaAlertsSource(BaseModel):
    """Task source: grafana-alerts."""

    type: Literal["grafana-alerts"]
    min_severity: Literal["info", "warning", "critical"] = "info"
    permitted_actions: list[PermittedAction] | None = None
    model: str | None = None


class ProactiveImprovementSource(BaseModel):
    """Task source: proactive-improvement."""

    type: Literal["proactive-improvement"]
    selection_strategy: Literal["agent-chooses", "harness-random"] = "agent-chooses"
    max_open_suggestions: int = 3
    targets: list[str] = Field(default_factory=list)
    permitted_actions: list[PermittedAction] | None = None
    model: str | None = None


# Union discriminated on `type`.
TaskSource = Annotated[
    GhDelegatedSource | GrafanaAlertsSource | ProactiveImprovementSource,
    Field(discriminator="type"),
]


# ── Project model ──────────────────────────────────────────────────────────────


class ProjectConfig(BaseModel):
    """Configuration for a single managed project."""

    name: str
    repo: str
    cron: str
    enabled: bool = True
    model: str | None = None
    max_turns: int | None = None
    timeout_s: int | None = None
    max_comments: int | None = None
    daily_budget_usd: float | None = None
    permitted_actions: list[PermittedAction] | None = None
    context: str | None = None
    task_sources: list[TaskSource] = Field(default_factory=list)


# ── Top-level config ───────────────────────────────────────────────────────────


class DigestConfig(BaseModel):
    """Global digest (Slack summary) configuration."""

    enabled: bool = True
    cron: str = "0 8 * * *"


class DefaultsConfig(BaseModel):
    """Global defaults inherited by all projects."""

    model: str = "claude-opus-4-7"
    max_turns: int = 20
    timeout_s: int = 600
    max_comments: int = 10


class LabroConfig(BaseModel):
    """Root config object parsed from labro.toml."""

    digest: DigestConfig = Field(default_factory=DigestConfig)
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)
    projects: list[ProjectConfig] = Field(default_factory=list)
