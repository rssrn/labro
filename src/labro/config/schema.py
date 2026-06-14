"""Pydantic models for labro.toml (full schema).

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator
from pydantic.functional_validators import AfterValidator, BeforeValidator


class PermittedAction(StrEnum):
    """Actions a Labro agent is allowed to perform on GitHub."""

    COMMENT_ON_ISSUE = "comment_on_issue"
    COMMENT_ON_PR = "comment_on_pr"
    OPEN_PR = "open_pr"
    MERGE_PR = "merge_pr"
    PUSH_DEFAULT = "push_default"
    CLOSE_ISSUE = "close_issue"
    CREATE_ISSUE = "create_issue"


# ── Model slug ─────────────────────────────────────────────────────────────────

_MODEL_SLUG_RE = re.compile(
    r"^[a-z][a-z0-9-]*"  # CLI id (e.g. "claude-code", "codex")
    r"(?:"
    r":[a-zA-Z0-9][a-zA-Z0-9._-]*"  # :provider-or-bare-model
    r"(?:/[a-zA-Z0-9][a-zA-Z0-9._/:-]*)?"  # /model — may contain extra slashes and colons
    r"(?:@[a-z][a-z0-9-]*)?"  # @effort (optional)
    r"|"
    r"@[a-z][a-z0-9-]*"  # @effort directly on CLI id (no model spec)
    r")?$"
)


def _validate_model_slug(v: str) -> str:
    # Detect bare legacy slugs (old format: "provider/model@effort") and give helpful error
    if "/" in v and not v.startswith(tuple("0123456789")) and ":" not in v.split("/")[0]:
        # Looks like "anthropic/claude-..." — suggest the new format
        raise ValueError(
            f"invalid model slug {v!r}: bare provider/model slugs are no longer valid. "
            f"Use CLI-prefixed form, e.g. 'claude-code:{v}'"
        )
    if not _MODEL_SLUG_RE.match(v):
        raise ValueError(
            f"invalid model slug {v!r}: expected '<cli>[:<provider>/<model>][@<effort>]', "
            f"e.g. 'claude-code', 'claude-code:anthropic/claude-opus-4-7@high', "
            f"'opencode:openrouter/openai/gpt-4o:free'"
        )
    return v


# Validated model-slug type. CLI-prefixed format: <cli>[:<provider>/<model>][@<effort>]
# The model component may contain extra slashes and colons for providers like OpenRouter
# whose model IDs use the form "org/model:variant" (e.g. "openai/gpt-4o:free").
# Examples: "claude-code", "claude-code@high", "claude-code:anthropic/claude-opus-4-7",
#           "claude-code:anthropic/claude-opus-4-7@high", "codex:openai/gpt-5-codex",
#           "opencode:openrouter/openai/gpt-oss-120b:free"
ModelSlug = Annotated[str, AfterValidator(_validate_model_slug)]


def _validate_non_empty_slug_list(v: list[str]) -> list[str]:
    if not v:
        raise ValueError("model slug list must not be empty")
    return v


ModelSlugList = Annotated[
    list[ModelSlug],
    BeforeValidator(lambda v: [v] if isinstance(v, str) else v),
    AfterValidator(_validate_non_empty_slug_list),
]


@dataclass
class ParsedSlug:
    """Components of a parsed model slug."""

    agent: str  # CLI id, e.g. "claude-code"
    provider: str | None  # vendor, e.g. "anthropic"
    model: str | None  # model name only, e.g. "claude-opus-4-7"
    effort: str | None  # e.g. "high"


def parse_slug(slug: str) -> ParsedSlug:
    """Parse a CLI-prefixed model slug into its four components.

    Assumes slug has already passed _validate_model_slug.
    """
    effort: str | None = None
    if "@" in slug:
        main, effort = slug.rsplit("@", 1)
    else:
        main = slug

    if ":" in main:
        agent_id, rest = main.split(":", 1)
        if "/" in rest:
            provider, model_name = rest.split("/", 1)
        else:
            provider = None
            model_name = rest
    else:
        agent_id = main
        provider = None
        model_name = None

    return ParsedSlug(agent=agent_id, provider=provider, model=model_name, effort=effort)


# ── Persona and shared-rule models ─────────────────────────────────────────────


class PersonaConfig(BaseModel):
    """A named persona: a prompt snippet prepended to the role section of every run."""

    prompt: str


class PerspectiveConfig(BaseModel):
    """A named perspective: a prompt lens injected into proactive-improvement runs."""

    prompt: str


class SharedRuleConfig(BaseModel):
    """A reusable label rule template, referenced by name from label_rules entries."""

    label: str
    done_label: str
    description: str | None = None
    persona: str | None = None
    permitted_actions: list[PermittedAction] | None = None
    model: ModelSlugList | None = None


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
    description: str | None = None
    persona: str | None = None
    permitted_actions: list[PermittedAction] | None = None
    model: ModelSlugList | None = None

    @model_validator(mode="after")
    def require_label_source(self) -> LabelRule:
        if self.rule is None and (self.label is None or self.done_label is None):
            raise ValueError(
                "label_rule must specify either 'rule' (a shared_rule name) "
                "or both 'label' and 'done_label' directly"
            )
        return self


class AuthorRule(BaseModel):
    """An author-based eligibility rule within a gh-author source."""

    actor: str
    done_label: str
    description: str | None = None
    persona: str | None = None
    model: ModelSlugList | None = None
    permitted_actions: list[PermittedAction] | None = None
    requires_dependabot_alert: bool = False
    """Only match PRs that fix an open Dependabot alert (security updates).

    Dependabot applies no label or marker distinguishing security-update PRs from
    routine version bumps, so the harness cross-references the Dependabot alerts
    API to tell them apart.  Use a security-only rule (``requires_dependabot_alert
    = true``) ahead of a plain routine-bump rule to prioritise security fixes.
    """


class GhLabelSource(BaseModel):
    """Task source: gh-label (label_rules only)."""

    type: Literal["gh-label"]
    label_rules: list[LabelRule] = Field(default_factory=list)
    permitted_actions: list[PermittedAction] | None = None
    model: ModelSlugList | None = None

    @model_validator(mode="after")
    def require_at_least_one_rule(self) -> GhLabelSource:
        """gh-label with no label_rules is a hard config error."""
        if not self.label_rules:
            raise ValueError("gh-label source must define at least one label_rule")
        return self


class GhAuthorSource(BaseModel):
    """Task source: gh-author (author_rules — items opened by a specific GitHub login)."""

    type: Literal["gh-author"]
    author_rules: list[AuthorRule] = Field(default_factory=list)
    permitted_actions: list[PermittedAction] | None = None
    model: ModelSlugList | None = None

    @model_validator(mode="after")
    def require_at_least_one_rule(self) -> GhAuthorSource:
        """gh-author with no author_rules is a hard config error."""
        if not self.author_rules:
            raise ValueError("gh-author source must define at least one author_rule")
        return self


class GrafanaAlertsSource(BaseModel):
    """Task source: grafana-alerts."""

    type: Literal["grafana-alerts"]
    min_severity: Literal["info", "warning", "critical"] = "info"
    persona: str | None = None
    permitted_actions: list[PermittedAction] | None = None
    model: ModelSlugList | None = None


class ProactiveImprovementSource(BaseModel):
    """Task source: proactive-improvement."""

    type: Literal["proactive-improvement"]
    max_open_suggestions: int = 3
    perspectives: list[str] = Field(default_factory=list)  # empty = use all defined
    persona: str | None = None
    permitted_actions: list[PermittedAction] | None = None
    model: ModelSlugList | None = None


# Union discriminated on `type`.
TaskSource = Annotated[
    GhLabelSource | GhAuthorSource | GrafanaAlertsSource | ProactiveImprovementSource,
    Field(discriminator="type"),
]


# ── Project model ──────────────────────────────────────────────────────────────


class ProjectConfig(BaseModel):
    """Configuration for a single managed project."""

    name: str
    repo: str
    cron: str
    enabled: bool = True
    model: ModelSlugList | None = None
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


class DashboardConfig(BaseModel):
    """Metrics dashboard publish configuration.

    @author Claude Sonnet 4.6 Anthropic
    """

    enabled: bool = False
    cron: str = "17 * * * *"
    key_prefix: str = ""
    title: str | None = None
    # Override endpoint (for testing); derived from R2_ACCOUNT_ID if None.
    endpoint: str | None = None
    redact: bool = False  # reserved, no-op in M9.1


class SignalsConfig(BaseModel):
    """Signal collection (back-fill outcome signals for items_touched rows).

    @author Claude Sonnet 4.6 Anthropic
    """

    enabled: bool = True
    cron: str = "0 6 * * *"


class DefaultsConfig(BaseModel):
    """Global defaults inherited by all projects."""

    model: ModelSlugList = Field(default_factory=lambda: ["claude-code:anthropic/claude-opus-4-7"])
    max_turns: int = 20
    timeout_s: int = 600
    max_comments: int = 10


class LabroConfig(BaseModel):
    """Root config object parsed from labro.toml."""

    personas: dict[str, PersonaConfig] = Field(default_factory=dict)
    perspectives: dict[str, PerspectiveConfig] = Field(default_factory=dict)
    shared_rules: dict[str, SharedRuleConfig] = Field(default_factory=dict)
    digest: DigestConfig = Field(default_factory=DigestConfig)
    dashboard: DashboardConfig = Field(default_factory=DashboardConfig)
    signals: SignalsConfig = Field(default_factory=SignalsConfig)
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)
    projects: list[ProjectConfig] = Field(default_factory=list)
    # GitHub App credentials (alternative to GH_TOKEN PAT).
    # Both must be set together, or neither.
    # The private key is passed via the GH_APP_PRIVATE_KEY env var (not in
    # this file — keep secrets out of labro.toml).
    # When set, GH_TOKEN is not required — labro generates a per-run
    # installation access token automatically.
    github_app_id: int | None = None
    github_app_name: str | None = None  # app slug, e.g. "labro-rssrn"

    @model_validator(mode="after")
    def validate_github_app(self) -> LabroConfig:
        """Require github_app_id and github_app_name to be set together or not at all."""
        has_id = self.github_app_id is not None
        has_name = self.github_app_name is not None
        if has_id != has_name:
            raise ValueError("github_app_id and github_app_name must be set together")
        return self

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
                        if rule.description is None and template.description is not None:
                            rule.description = template.description
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
                elif isinstance(source, GhAuthorSource):
                    for arule in source.author_rules:
                        if arule.persona is not None and arule.persona not in self.personas:
                            raise ValueError(
                                f"persona {arule.persona!r} is not defined in [personas]"
                            )
                elif isinstance(source, GrafanaAlertsSource | ProactiveImprovementSource):
                    if source.persona is not None and source.persona not in self.personas:
                        raise ValueError(
                            f"persona {source.persona!r} is not defined in [personas]"
                        )
                    if isinstance(source, ProactiveImprovementSource):
                        for pname in source.perspectives:
                            if pname not in self.perspectives:
                                raise ValueError(
                                    f"perspective {pname!r} is not defined in [perspectives]"
                                )

        return self
