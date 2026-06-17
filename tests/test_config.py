"""Tests for config schema and loader.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from labro.config.loader import ConfigError, load_config
from labro.config.schema import LabroConfig, PermittedAction

# ── helpers ────────────────────────────────────────────────────────────────────


def write_toml(tmp_path: Path, content: str) -> Path:
    """Write *content* to a labro.toml under *tmp_path* and return the path."""
    p = tmp_path / "labro.toml"
    p.write_text(textwrap.dedent(content))
    return p


MINIMAL_VALID_TOML = """\
[digest]
enabled = false

[[projects]]
name    = "my-api"
repo    = "my-org/my-api"
cron    = "0 * * * *"

[[projects.task_sources]]
type = "gh-label"

[[projects.task_sources.label_rules]]
label      = "ai-dev"
done_label = "ai-dev-done"
permitted_actions = ["comment_on_issue", "open_pr"]
"""


# ── valid config tests ─────────────────────────────────────────────────────────


def test_load_valid_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A well-formed config with required env vars set loads without error."""
    monkeypatch.setenv("GH_TOKEN", "ghp_test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    # digest.enabled = false → SLACK_WEBHOOK_URL not required

    p = write_toml(tmp_path, MINIMAL_VALID_TOML)
    config = load_config(p)

    assert isinstance(config, LabroConfig)
    assert config.projects[0].name == "my-api"
    assert config.projects[0].repo == "my-org/my-api"


# ── ModelSlugList tests ──────────────────────────────────────────────────────────


def test_model_slug_list_coerces_string_to_list() -> None:
    """A bare string in a model field is coerced to a single-element list."""
    from labro.config.schema import DefaultsConfig

    d = DefaultsConfig(model="claude-code:anthropic/claude-opus-4-7")  # type: ignore[arg-type]
    assert d.model == ["claude-code:anthropic/claude-opus-4-7"]


def test_model_slug_list_accepts_array() -> None:
    """An array in a model field is accepted as-is."""
    from labro.config.schema import DefaultsConfig

    slugs = ["claude-code:anthropic/claude-opus-4-7", "claude-code:anthropic/claude-sonnet-4-6"]
    d = DefaultsConfig(model=slugs)
    assert d.model == slugs


def test_defaults_config_default_is_list() -> None:
    """DefaultsConfig.model default factory produces a list."""
    from labro.config.schema import DefaultsConfig

    d = DefaultsConfig()
    assert isinstance(d.model, list)
    assert len(d.model) == 1
    assert d.model[0] == "claude-code:anthropic/claude-opus-4-7"


def test_model_slug_list_rejects_empty_list() -> None:
    """An empty model list raises a validation error."""
    from pydantic import ValidationError

    from labro.config.schema import DefaultsConfig

    with pytest.raises(ValidationError, match="must not be empty"):
        DefaultsConfig(model=[])


def test_defaults_inherited(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """[defaults] values are present in the parsed config."""
    monkeypatch.setenv("GH_TOKEN", "ghp_test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    p = write_toml(
        tmp_path,
        """\
        [digest]
        enabled = false

        [defaults]
        model     = "claude-code:anthropic/claude-sonnet-4-6"
        max_turns = 15
        timeout_s = 300

        [[projects]]
        name    = "svc"
        repo    = "org/svc"
        cron    = "0 * * * *"

        [[projects.task_sources]]
        type = "gh-label"

        [[projects.task_sources.label_rules]]
        label      = "ai-fix"
        done_label = "ai-fix-done"
        """,
    )
    config = load_config(p)
    assert config.defaults.model == ["claude-code:anthropic/claude-sonnet-4-6"]
    assert config.defaults.max_turns == 15
    assert config.defaults.timeout_s == 300


def test_permitted_actions_parsed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """All valid permitted_actions values are accepted and mapped to the enum."""
    monkeypatch.setenv("GH_TOKEN", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")

    p = write_toml(
        tmp_path,
        """\
        [digest]
        enabled = false

        [[projects]]
        name    = "svc"
        repo    = "org/svc"
        cron    = "0 * * * *"
        permitted_actions = [
            "comment_on_issue", "comment_on_pr", "open_pr",
            "merge_pr", "push_default", "close_issue", "create_issue"
        ]

        [[projects.task_sources]]
        type = "gh-label"

        [[projects.task_sources.label_rules]]
        label      = "ai-dev"
        done_label = "ai-done"
        """,
    )
    config = load_config(p)
    assert PermittedAction.OPEN_PR in (config.projects[0].permitted_actions or [])


def test_digest_enabled_requires_slack_webhook(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When digest is enabled, SLACK_WEBHOOK_URL must be present."""
    monkeypatch.setenv("GH_TOKEN", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)

    p = write_toml(
        tmp_path,
        """\
        [digest]
        enabled = true
        cron    = "0 8 * * *"

        [[projects]]
        name    = "svc"
        repo    = "org/svc"
        cron    = "0 * * * *"

        [[projects.task_sources]]
        type = "gh-label"

        [[projects.task_sources.label_rules]]
        label      = "ai-dev"
        done_label = "ai-done"
        """,
    )
    with pytest.raises(ConfigError, match="SLACK_WEBHOOK_URL"):
        load_config(p)


def test_grafana_source_requires_grafana_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A grafana-alerts source requires GRAFANA_TOKEN."""
    monkeypatch.setenv("GH_TOKEN", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/x")
    monkeypatch.delenv("GRAFANA_TOKEN", raising=False)

    p = write_toml(
        tmp_path,
        """\
        [[projects]]
        name    = "svc"
        repo    = "org/svc"
        cron    = "0 * * * *"

        [[projects.task_sources]]
        type         = "grafana-alerts"
        min_severity = "critical"
        permitted_actions = ["create_issue"]
        """,
    )
    with pytest.raises(ConfigError, match="GRAFANA_TOKEN"):
        load_config(p)


# ── hard error: unknown permitted_action ───────────────────────────────────────


def test_unknown_permitted_action_is_hard_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unrecognised permitted_actions value raises ConfigError at load time."""
    monkeypatch.setenv("GH_TOKEN", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")

    p = write_toml(
        tmp_path,
        """\
        [digest]
        enabled = false

        [[projects]]
        name    = "svc"
        repo    = "org/svc"
        cron    = "0 * * * *"
        permitted_actions = ["comment_on_issue", "fly_to_moon"]

        [[projects.task_sources]]
        type = "gh-label"

        [[projects.task_sources.label_rules]]
        label      = "ai-dev"
        done_label = "ai-done"
        """,
    )
    with pytest.raises(ConfigError):
        load_config(p)


# ── hard error: gh-label with no rules ────────────────────────────────────


def test_gh_label_no_rules_is_hard_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """gh-label with no label_rules raises ConfigError."""
    monkeypatch.setenv("GH_TOKEN", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")

    p = write_toml(
        tmp_path,
        """\
        [digest]
        enabled = false

        [[projects]]
        name    = "svc"
        repo    = "org/svc"
        cron    = "0 * * * *"

        [[projects.task_sources]]
        type = "gh-label"
        """,
    )
    with pytest.raises(ConfigError, match="at least one label_rule"):
        load_config(p)


def test_gh_author_source_loads(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A well-formed gh-author source with an author_rule loads without error."""
    monkeypatch.setenv("GH_TOKEN", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")

    p = write_toml(
        tmp_path,
        """\
        [digest]
        enabled = false

        [[projects]]
        name = "svc"
        repo = "org/svc"
        cron = "0 * * * *"

        [[projects.task_sources]]
        type = "gh-author"

        [[projects.task_sources.author_rules]]
        actor      = "dependabot[bot]"
        done_label = "dependencies-merged"
        permitted_actions = ["comment_on_pr"]
        """,
    )
    config = load_config(p)
    from labro.config.schema import GhAuthorSource

    src = config.projects[0].task_sources[0]
    assert isinstance(src, GhAuthorSource)
    assert src.author_rules[0].actor == "dependabot[bot]"


def test_gh_author_no_rules_is_hard_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """gh-author with no author_rules raises ConfigError."""
    monkeypatch.setenv("GH_TOKEN", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")

    p = write_toml(
        tmp_path,
        """\
        [digest]
        enabled = false

        [[projects]]
        name    = "svc"
        repo    = "org/svc"
        cron    = "0 * * * *"

        [[projects.task_sources]]
        type = "gh-author"
        """,
    )
    with pytest.raises(ConfigError, match="at least one author_rule"):
        load_config(p)


# ── hard error: missing required env vars ─────────────────────────────────────


def test_missing_gh_token_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Absent GH_TOKEN raises ConfigError naming the variable."""
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")

    p = write_toml(tmp_path, MINIMAL_VALID_TOML)
    with pytest.raises(ConfigError, match="GH_TOKEN"):
        load_config(p)


def test_missing_claude_auth_warns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Missing agent credentials emit a warning but do not raise ConfigError."""
    monkeypatch.setenv("GH_TOKEN", "x")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)

    p = write_toml(tmp_path, MINIMAL_VALID_TOML)
    import logging

    with caplog.at_level(logging.WARNING, logger="labro.config.loader"):
        config = load_config(p)
    assert isinstance(config, LabroConfig)
    assert any("claude-code" in r.message for r in caplog.records)


def test_oauth_token_satisfies_claude_auth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CLAUDE_CODE_OAUTH_TOKEN alone (no ANTHROPIC_API_KEY) is accepted."""
    monkeypatch.setenv("GH_TOKEN", "x")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "oauth-token-value")

    p = write_toml(tmp_path, MINIMAL_VALID_TOML)
    config = load_config(p)
    assert isinstance(config, LabroConfig)


def test_missing_file_raises(tmp_path: Path) -> None:
    """A non-existent config path raises ConfigError."""
    with pytest.raises(ConfigError, match="Cannot read config file"):
        load_config(tmp_path / "nonexistent.toml")


def test_invalid_toml_syntax_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Malformed TOML raises ConfigError."""
    p = tmp_path / "labro.toml"
    p.write_text("[[not valid toml ]] = bad")
    with pytest.raises(ConfigError, match="TOML parse error"):
        load_config(p)


# ── personas and shared_rules ─────────────────────────────────────────────────


def test_personas_parsed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """personas section is loaded into a dict keyed by slug."""
    monkeypatch.setenv("GH_TOKEN", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")

    p = write_toml(
        tmp_path,
        """\
        [digest]
        enabled = false

        [personas.senior-developer]
        prompt = "Act as a senior developer."

        [personas.business-analyst]
        prompt = "Act as a business analyst."

        [[projects]]
        name = "svc"
        repo = "org/svc"
        cron = "0 * * * *"

        [[projects.task_sources]]
        type = "gh-label"

        [[projects.task_sources.label_rules]]
        label      = "ai-dev"
        done_label = "ai-dev-done"
        """,
    )
    config = load_config(p)
    assert "senior-developer" in config.personas
    assert config.personas["senior-developer"].prompt == "Act as a senior developer."
    assert "business-analyst" in config.personas


def test_shared_rule_reference_resolved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A label_rule with rule= gets label/done_label from the shared_rule."""
    monkeypatch.setenv("GH_TOKEN", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")

    p = write_toml(
        tmp_path,
        """\
        [digest]
        enabled = false

        [personas.dev]
        prompt = "Act as a developer."

        [shared_rules.dev]
        label      = "ai-dev"
        done_label = "ai-dev-done"
        persona    = "dev"
        permitted_actions = ["comment_on_issue", "open_pr"]

        [[projects]]
        name = "svc"
        repo = "org/svc"
        cron = "0 * * * *"

        [[projects.task_sources]]
        type = "gh-label"

        [[projects.task_sources.label_rules]]
        rule = "dev"
        """,
    )
    config = load_config(p)
    source = config.projects[0].task_sources[0]
    rule = source.label_rules[0]  # type: ignore[union-attr]
    assert rule.label == "ai-dev"
    assert rule.done_label == "ai-dev-done"
    assert rule.persona == "dev"
    assert rule.permitted_actions is not None
    assert PermittedAction.OPEN_PR in rule.permitted_actions


def test_project_level_overrides_shared_rule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fields set on the label_rule take precedence over the shared_rule."""
    monkeypatch.setenv("GH_TOKEN", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")

    p = write_toml(
        tmp_path,
        """\
        [digest]
        enabled = false

        [personas.dev]
        prompt = "Act as a developer."

        [personas.junior-dev]
        prompt = "Act as a junior developer."

        [shared_rules.dev]
        label      = "ai-dev"
        done_label = "ai-dev-done"
        persona    = "dev"
        permitted_actions = ["comment_on_issue"]

        [[projects]]
        name = "svc"
        repo = "org/svc"
        cron = "0 * * * *"

        [[projects.task_sources]]
        type = "gh-label"

        [[projects.task_sources.label_rules]]
        rule              = "dev"
        persona           = "junior-dev"
        permitted_actions = ["comment_on_issue", "open_pr"]
        """,
    )
    config = load_config(p)
    source = config.projects[0].task_sources[0]
    rule = source.label_rules[0]  # type: ignore[union-attr]
    assert rule.persona == "junior-dev"  # overridden
    assert rule.permitted_actions is not None
    assert PermittedAction.OPEN_PR in rule.permitted_actions  # overridden


def test_undefined_shared_rule_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Referencing a shared_rule name that doesn't exist raises ConfigError."""
    monkeypatch.setenv("GH_TOKEN", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")

    p = write_toml(
        tmp_path,
        """\
        [digest]
        enabled = false

        [[projects]]
        name = "svc"
        repo = "org/svc"
        cron = "0 * * * *"

        [[projects.task_sources]]
        type = "gh-label"

        [[projects.task_sources.label_rules]]
        rule = "nonexistent"
        """,
    )
    with pytest.raises(ConfigError, match="nonexistent"):
        load_config(p)


def test_shared_rule_description_inherited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """description on a shared_rule is inherited by the referencing label_rule."""
    monkeypatch.setenv("GH_TOKEN", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")

    p = write_toml(
        tmp_path,
        """\
        [digest]
        enabled = false

        [shared_rules.dev]
        label       = "ai-dev"
        done_label  = "ai-dev-done"
        description = "AI Dev"

        [[projects]]
        name = "svc"
        repo = "org/svc"
        cron = "0 * * * *"

        [[projects.task_sources]]
        type = "gh-label"

        [[projects.task_sources.label_rules]]
        rule = "dev"
        """,
    )
    config = load_config(p)
    source = config.projects[0].task_sources[0]
    rule = source.label_rules[0]  # type: ignore[union-attr]
    assert rule.description == "AI Dev"


def test_label_rule_description_overrides_shared_rule(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An explicit description on a label_rule takes precedence over the shared_rule."""
    monkeypatch.setenv("GH_TOKEN", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")

    p = write_toml(
        tmp_path,
        """\
        [digest]
        enabled = false

        [shared_rules.dev]
        label       = "ai-dev"
        done_label  = "ai-dev-done"
        description = "Shared Description"

        [[projects]]
        name = "svc"
        repo = "org/svc"
        cron = "0 * * * *"

        [[projects.task_sources]]
        type = "gh-label"

        [[projects.task_sources.label_rules]]
        rule        = "dev"
        description = "Override Description"
        """,
    )
    config = load_config(p)
    source = config.projects[0].task_sources[0]
    rule = source.label_rules[0]  # type: ignore[union-attr]
    assert rule.description == "Override Description"


def test_undefined_persona_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Referencing a persona name that doesn't exist raises ConfigError."""
    monkeypatch.setenv("GH_TOKEN", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")

    p = write_toml(
        tmp_path,
        """\
        [digest]
        enabled = false

        [[projects]]
        name = "svc"
        repo = "org/svc"
        cron = "0 * * * *"

        [[projects.task_sources]]
        type = "gh-label"

        [[projects.task_sources.label_rules]]
        label      = "ai-dev"
        done_label = "ai-dev-done"
        persona    = "ghost"
        """,
    )
    with pytest.raises(ConfigError, match="ghost"):
        load_config(p)


def test_inline_label_rule_no_persona(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Inline label rules without personas still work (personas are optional)."""
    monkeypatch.setenv("GH_TOKEN", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")

    p = write_toml(tmp_path, MINIMAL_VALID_TOML)
    config = load_config(p)
    source = config.projects[0].task_sources[0]
    rule = source.label_rules[0]  # type: ignore[union-attr]
    assert rule.persona is None


def test_grafana_source_persona(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A grafana-alerts source accepts a persona field."""
    monkeypatch.setenv("GH_TOKEN", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("GRAFANA_TOKEN", "x")
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/x")

    p = write_toml(
        tmp_path,
        """\
        [personas.frontline-support]
        prompt = "Act as a support engineer."

        [[projects]]
        name = "svc"
        repo = "org/svc"
        cron = "0 * * * *"

        [[projects.task_sources]]
        type         = "grafana-alerts"
        min_severity = "critical"
        persona      = "frontline-support"
        permitted_actions = ["create_issue"]
        """,
    )
    config = load_config(p)
    source = config.projects[0].task_sources[0]
    from labro.config.schema import GrafanaAlertsSource

    assert isinstance(source, GrafanaAlertsSource)
    assert source.persona == "frontline-support"


def test_grafana_undefined_persona_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A grafana-alerts source referencing an undefined persona raises ConfigError."""
    monkeypatch.setenv("GH_TOKEN", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("GRAFANA_TOKEN", "x")
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/x")

    p = write_toml(
        tmp_path,
        """\
        [[projects]]
        name = "svc"
        repo = "org/svc"
        cron = "0 * * * *"

        [[projects.task_sources]]
        type         = "grafana-alerts"
        min_severity = "critical"
        persona      = "ghost"
        permitted_actions = ["create_issue"]
        """,
    )
    with pytest.raises(ConfigError, match="ghost"):
        load_config(p)


# ── GitHub App config ──────────────────────────────────────────────────────────


_APP_PROJECT_TOML = """\
[[projects]]
name = "p"
repo = "o/r"
cron = "0 * * * *"

[[projects.task_sources]]
type = "gh-label"

[[projects.task_sources.label_rules]]
label = "ai-dev"
done_label = "ai-dev-done"
permitted_actions = ["comment_on_issue"]
"""


_APP_TOML = textwrap.dedent(f"""\
    github_app_id = 12345
    github_app_name = "labro-rssrn"

    [digest]
    enabled = false

    {_APP_PROJECT_TOML}
    """)


class TestGitHubAppConfig:
    def test_app_fields_load_successfully(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.setenv("GH_APP_PRIVATE_KEY", "fake-pem")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

        p = write_toml(tmp_path, _APP_TOML)
        config = load_config(p)

        assert config.github_app_id == 12345
        assert config.github_app_name == "labro-rssrn"

    def test_no_gh_token_required_with_app_auth(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """GH_TOKEN must not be required when GitHub App auth is configured."""
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.setenv("GH_APP_PRIVATE_KEY", "fake-pem")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

        p = write_toml(tmp_path, _APP_TOML)
        config = load_config(p)  # must not raise
        assert config.github_app_id == 12345

    def test_missing_private_key_env_var_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """GH_APP_PRIVATE_KEY must be set when using GitHub App auth."""
        monkeypatch.delenv("GH_TOKEN", raising=False)
        monkeypatch.delenv("GH_APP_PRIVATE_KEY", raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

        p = write_toml(tmp_path, _APP_TOML)
        with pytest.raises(ConfigError, match="GH_APP_PRIVATE_KEY"):
            load_config(p)

    def test_partial_app_fields_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GH_TOKEN", "ghp_test")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        content = textwrap.dedent(f"""\
            github_app_id = 12345

            [digest]
            enabled = false

            {_APP_PROJECT_TOML}
            """)
        p = write_toml(tmp_path, content)
        with pytest.raises(ConfigError, match="must be set together"):
            load_config(p)


# ── Perspectives tests ─────────────────────────────────────────────────────────

_PROACTIVE_TOML = """\
[digest]
enabled = false

[[projects]]
name = "svc"
repo = "org/svc"
cron = "0 * * * *"

[[projects.task_sources]]
type = "proactive-improvement"
"""

_PERSPECTIVES_TOML = """\
[perspectives.red-team]
prompt = "Look for failures."

[perspectives.pre-mortem]
prompt = "Assume it fails."
"""


class TestPerspectives:
    def test_perspectives_loaded_from_separate_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GH_TOKEN", "ghp_test")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        p = write_toml(tmp_path, _PROACTIVE_TOML)
        (tmp_path / "perspectives.toml").write_text(_PERSPECTIVES_TOML)
        config = load_config(p)
        assert "red-team" in config.perspectives
        assert "pre-mortem" in config.perspectives
        assert config.perspectives["red-team"].prompt == "Look for failures."

    def test_missing_perspectives_file_does_not_raise(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GH_TOKEN", "ghp_test")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        p = write_toml(tmp_path, _PROACTIVE_TOML)
        # No perspectives.toml written — should load cleanly.
        config = load_config(p)
        assert config.perspectives == {}

    def test_unknown_perspective_name_in_source_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GH_TOKEN", "ghp_test")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        toml_with_unknown = _PROACTIVE_TOML + 'perspectives = ["nonexistent"]\n'
        p = write_toml(tmp_path, toml_with_unknown)
        with pytest.raises(ConfigError, match="perspective"):
            load_config(p)

    def test_valid_source_perspectives_subset_accepted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GH_TOKEN", "ghp_test")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        toml_with_subset = _PROACTIVE_TOML + 'perspectives = ["red-team"]\n'
        p = write_toml(tmp_path, toml_with_subset)
        (tmp_path / "perspectives.toml").write_text(_PERSPECTIVES_TOML)
        config = load_config(p)
        source = config.projects[0].task_sources[0]
        assert source.perspectives == ["red-team"]  # type: ignore[union-attr]


# ── DashboardConfig ────────────────────────────────────────────────────────────


class TestDashboardConfig:
    def test_dashboard_disabled_by_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GH_TOKEN", "ghp_test")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        p = write_toml(tmp_path, MINIMAL_VALID_TOML)
        config = load_config(p)
        assert not config.dashboard.enabled

    def test_dashboard_enabled_accepted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GH_TOKEN", "ghp_test")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        monkeypatch.setenv("R2_ACCESS_KEY_ID", "kid")
        monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "secret")
        monkeypatch.setenv("R2_ACCOUNT_ID", "acct")
        monkeypatch.setenv("R2_BUCKET", "my-bucket")
        toml = MINIMAL_VALID_TOML + "\n[dashboard]\nenabled = true\n"
        p = write_toml(tmp_path, toml)
        config = load_config(p)
        assert config.dashboard.enabled

    def test_dashboard_required_env_vars(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """R2_* vars are NOT in required_env_vars — they are checked by publish-db only."""
        from labro.config.loader import required_env_vars
        from labro.config.schema import DashboardConfig, DefaultsConfig, DigestConfig, LabroConfig

        config = LabroConfig(
            digest=DigestConfig(enabled=False),
            dashboard=DashboardConfig(enabled=True),
            defaults=DefaultsConfig(),
        )
        required = required_env_vars(config)
        for var in ("R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_ACCOUNT_ID", "R2_BUCKET"):
            assert var not in required

    def test_dashboard_disabled_no_r2_vars_required(self) -> None:
        """When dashboard.enabled = false, R2_* vars are NOT required."""
        from labro.config.loader import required_env_vars
        from labro.config.schema import DashboardConfig, DefaultsConfig, DigestConfig, LabroConfig

        config = LabroConfig(
            digest=DigestConfig(enabled=False),
            dashboard=DashboardConfig(enabled=False),
            defaults=DefaultsConfig(),
        )
        required = required_env_vars(config)
        for var in ("R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_ACCOUNT_ID", "R2_BUCKET"):
            assert var not in required
