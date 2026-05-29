"""Pydantic models for labro.toml (full schema).

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator


class PermittedAction(StrEnum):
    """Actions a Labro agent is allowed to perform on GitHub."""

    COMMENT_ON_ISSUE = "comment_on_issue"
    COMMENT_ON_PR = "comment_on_pr"
    OPEN_PR = "open_pr"
    MERGE_PR = "merge_pr"
    PUSH_DEFAULT = "push_default"
    CLOSE_ISSUE = "close_issue"
    CREATE_ISSUE = "create_issue"


# ── Persona and shared-rule models ─────────────────────────────────────────────


class PersonaConfig(BaseModel):
    """A named persona: a prompt snippet prepended to the role section of every run."""

    prompt: str


class SharedRuleConfig(BaseModel):
    """A reusable label rule template, referenced by name from label_rules entries."""

    label: str
    done_label: str
    persona: str | None = None
    permitted_actions: list[PermittedAction] | None = None
    model: str | None = None


# ── Task source models ─────────────────────────────────────────────────────────


class LabelRule(BaseModel):
    """A single label-based eligibility rule within a gh-label source.

    Either provide ``rule`` (a shared_rule name) and any overrides, or specify
    ``label`` and ``done_label`` directly.  Per-rule fields always take
    precedence over values inherited from a shared rule.
    """

    rule: str | None = None
    label: str | None = None
    done_label: str | None = None
    persona: str | None = None
    permitted_actions: list[PermittedAction] | None = None
    model: str | None = None

    @model_validator(mode="after")
    def require_label_source(self) -> LabelRule:
        if self.rule is None and (self.label is None or self.done_label is None):
            raise ValueError(
                "label_rule must specify either 'rule' (a shared_rule name) "
                "or both 'label' and 'done_label' directly"
            )
        return self


class ActorRule(BaseModel):
    """An actor-based eligibility rule within a gh-label source."""

    actor: str
    done_label: str
    persona: str | None = None
    model: str | None = None
    permitted_actions: list[PermittedAction] | None = None


class GhLabelSource(BaseModel):
    """Task source: gh-label (label_rules and/or actor_rules)."""

    type: Literal["gh-label"]
    label_rules: list[LabelRule] = Field(default_factory=list)
    actor_rules: list[ActorRule] = Field(default_factory=list)
    permitted_actions: list[PermittedAction] | None = None
    model: str | None = None

    @model_validator(mode="after")
    def require_at_least_one_rule(self) -> GhLabelSource:
        """gh-label with no rules is a hard config error."""
        if not self.label_rules and not self.actor_rules:
            raise ValueError("gh-label source must define at least one label_rule or actor_rule")
        return self


class GrafanaAlertsSource(BaseModel):
    """Task source: grafana-alerts."""

    type: Literal["grafana-alerts"]
    min_severity: Literal["info", "warning", "critical"] = "info"
    persona: str | None = None
    permitted_actions: list[PermittedAction] | None = None
    model: str | None = None


class ProactiveImprovementSource(BaseModel):
    """Task source: proactive-improvement."""

    type: Literal["proactive-improvement"]
    selection_strategy: Literal["agent-chooses", "harness-random"] = "agent-chooses"
    max_open_suggestions: int = 3
    targets: list[str] = Field(default_factory=list)
    persona: str | None = None
    permitted_actions: list[PermittedAction] | None = None
    model: str | None = None


# Union discriminated on `type`.
TaskSource = Annotated[
    GhLabelSource | GrafanaAlertsSource | ProactiveImprovementSource,
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

    personas: dict[str, PersonaConfig] = Field(default_factory=dict)
    shared_rules: dict[str, SharedRuleConfig] = Field(default_factory=dict)
    digest: DigestConfig = Field(default_factory=DigestConfig)
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)
    projects: list[ProjectConfig] = Field(default_factory=list)

    @model_validator(mode="after")
    def resolve_and_validate_rules(self) -> LabroConfig:
        """Expand shared_rule references and validate persona references."""
        for project in self.projects:
            for source in project.task_sources:
                if not isinstance(source, GhLabelSource):
                    continue
                for rule in source.label_rules:
                    if rule.rule is not None:
                        template = self.shared_rules.get(rule.rule)
                        if template is None:
                            raise ValueError(
                                f"label_rule references shared_rule {rule.rule!r} "
                                f"which is not defined in [shared_rules]"
                            )
                        if rule.label is None:
                            rule.label = template.label
                        if rule.done_label is None:
                            rule.done_label = template.done_label
                        if rule.persona is None and template.persona is not None:
                            rule.persona = template.persona
                        if (
                            rule.permitted_actions is None
                            and template.permitted_actions is not None
                        ):
                            rule.permitted_actions = template.permitted_actions
                        if rule.model is None and template.model is not None:
                            rule.model = template.model

        # Validate all persona references across every source type.
        for project in self.projects:
            for source in project.task_sources:
                if isinstance(source, GhLabelSource):
                    for lrule in source.label_rules:
                        if lrule.persona is not None and lrule.persona not in self.personas:
                            raise ValueError(
                                f"persona {lrule.persona!r} is not defined in [personas]"
                            )
                    for arule in source.actor_rules:
                        if arule.persona is not None and arule.persona not in self.personas:
                            raise ValueError(
                                f"persona {arule.persona!r} is not defined in [personas]"
                            )
                elif isinstance(source, GrafanaAlertsSource | ProactiveImprovementSource):
                    if source.persona is not None and source.persona not in self.personas:
                        raise ValueError(
                            f"persona {source.persona!r} is not defined in [personas]"
                        )

        return self
