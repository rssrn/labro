"""Tests for the agent registry and multi-provider support.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import pytest

from labro.agents.registry import all_agents, get_agent
from labro.config.schema import parse_slug

# ── parse_slug ────────────────────────────────────────────────────────────────


def test_parse_slug_cli_only() -> None:
    p = parse_slug("claude-code")
    assert p.agent == "claude-code"
    assert p.provider is None
    assert p.model is None
    assert p.effort is None


def test_parse_slug_cli_at_effort() -> None:
    p = parse_slug("claude-code@high")
    assert p.agent == "claude-code"
    assert p.provider is None
    assert p.model is None
    assert p.effort == "high"


def test_parse_slug_cli_bare_model() -> None:
    p = parse_slug("claude-code:claude-opus-4-7")
    assert p.agent == "claude-code"
    assert p.provider is None
    assert p.model == "claude-opus-4-7"
    assert p.effort is None


def test_parse_slug_full() -> None:
    p = parse_slug("claude-code:anthropic/claude-opus-4-7@high")
    assert p.agent == "claude-code"
    assert p.provider == "anthropic"
    assert p.model == "claude-opus-4-7"
    assert p.effort == "high"


def test_parse_slug_codex_full() -> None:
    p = parse_slug("codex:openai/gpt-5-codex@high")
    assert p.agent == "codex"
    assert p.provider == "openai"
    assert p.model == "gpt-5-codex"
    assert p.effort == "high"


def test_parse_slug_no_effort() -> None:
    p = parse_slug("claude-code:anthropic/claude-opus-4-7")
    assert p.effort is None
    assert p.model == "claude-opus-4-7"


# ── slug validation ───────────────────────────────────────────────────────────


def test_legacy_slug_raises() -> None:
    from labro.config.schema import _validate_model_slug

    with pytest.raises(ValueError, match="CLI-prefixed"):
        _validate_model_slug("anthropic/claude-opus-4-7")


def test_legacy_slug_with_effort_raises() -> None:
    from labro.config.schema import _validate_model_slug

    with pytest.raises(ValueError, match="CLI-prefixed"):
        _validate_model_slug("anthropic/claude-opus-4-7@high")


def test_invalid_slug_raises() -> None:
    from labro.config.schema import _validate_model_slug

    with pytest.raises(ValueError, match="invalid model slug"):
        _validate_model_slug("UPPERCASE")


# ── registry ──────────────────────────────────────────────────────────────────


def test_get_agent_claude_code() -> None:
    agent = get_agent("claude-code")
    assert agent.id == "claude-code"


def test_get_agent_codex() -> None:
    agent = get_agent("codex")
    assert agent.id == "codex"


def test_get_agent_unknown_raises() -> None:
    with pytest.raises(ValueError, match="Unknown agent"):
        get_agent("does-not-exist")


def test_all_agents_covers_both() -> None:
    ids = {a.id for a in all_agents()}
    assert "claude-code" in ids
    assert "codex" in ids
