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
type = "gh-delegated"

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
        model     = "claude-sonnet-4-6"
        max_turns = 15
        timeout_s = 300

        [[projects]]
        name    = "svc"
        repo    = "org/svc"
        cron    = "0 * * * *"

        [[projects.task_sources]]
        type = "gh-delegated"

        [[projects.task_sources.label_rules]]
        label      = "ai-fix"
        done_label = "ai-fix-done"
        """,
    )
    config = load_config(p)
    assert config.defaults.model == "claude-sonnet-4-6"
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
        type = "gh-delegated"

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
        type = "gh-delegated"

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
        type = "gh-delegated"

        [[projects.task_sources.label_rules]]
        label      = "ai-dev"
        done_label = "ai-done"
        """,
    )
    with pytest.raises(ConfigError):
        load_config(p)


# ── hard error: gh-delegated with no rules ────────────────────────────────────


def test_gh_delegated_no_rules_is_hard_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """gh-delegated with neither label_rules nor actor_rules raises ConfigError."""
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
        type = "gh-delegated"
        """,
    )
    with pytest.raises(ConfigError, match="at least one label_rule or actor_rule"):
        load_config(p)


# ── hard error: missing required env vars ─────────────────────────────────────


def test_missing_gh_token_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Absent GH_TOKEN raises ConfigError naming the variable."""
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")

    p = write_toml(tmp_path, MINIMAL_VALID_TOML)
    with pytest.raises(ConfigError, match="GH_TOKEN"):
        load_config(p)


def test_missing_anthropic_key_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Absent ANTHROPIC_API_KEY raises ConfigError naming the variable."""
    monkeypatch.setenv("GH_TOKEN", "x")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    p = write_toml(tmp_path, MINIMAL_VALID_TOML)
    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
        load_config(p)


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
