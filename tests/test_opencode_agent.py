"""Tests for the OpenCode agent implementation.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from labro.agents.opencode import (
    OpenCodeAgent,
    _build_config,
    _parse_result,
    _strip_fences,
)
from labro.models import AgentConfig

# ── fixtures ──────────────────────────────────────────────────────────────────

_AGENT = OpenCodeAgent()

_BASE_CONFIG = AgentConfig.from_slug(
    "opencode:openrouter/qwen-3",
    max_turns=5,
    timeout_s=120,
)

_FULL_SO = {
    "outcome": "success",
    "summary": "Fixed the bug.",
    "actions_taken": ["Edited src/main.py"],
    "items_created": [],
    "failure_reason": None,
}


def _make_event_stream(*events: dict[str, Any]) -> bytes:
    return "\n".join(json.dumps(e) for e in events).encode()


def _text_event(text: str, synthetic: bool = False) -> dict[str, Any]:
    # Real opencode events wrap data inside a "part" object.
    return {"type": "text", "part": {"type": "text", "text": text, "synthetic": synthetic}}


def _step_finish_event(
    input_tokens: int = 10,
    output_tokens: int = 20,
    cache_read: int = 5,
    cache_write: int = 2,
    cost: float = 0.001,
) -> dict[str, Any]:
    return {
        "type": "step_finish",
        "part": {
            "type": "step-finish",
            "tokens": {
                "input": input_tokens,
                "output": output_tokens,
                "cache": {"read": cache_read, "write": cache_write},
            },
            "cost": cost,
        },
    }


# ── auth ──────────────────────────────────────────────────────────────────────


def test_has_auth_always_true() -> None:
    assert _AGENT.has_auth() is True


def test_has_auth_true_even_without_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in _AGENT.auth_env_vars:
        monkeypatch.delenv(var, raising=False)
    assert _AGENT.has_auth() is True


def test_validate_auth_warn_when_key_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    status, msg = _AGENT.validate_auth()
    assert status == "WARN"
    assert "OPENROUTER_API_KEY" in msg


def test_validate_auth_warn_when_no_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in _AGENT.auth_env_vars:
        monkeypatch.delenv(var, raising=False)
    status, msg = _AGENT.validate_auth()
    assert status == "WARN"
    assert "no known provider" in msg


# ── config generation ─────────────────────────────────────────────────────────


def test_build_config_with_provider() -> None:
    cfg = json.loads(_build_config(_BASE_CONFIG))
    assert cfg["permission"] == {"*": "allow"}
    assert "openrouter" in cfg["provider"]
    assert cfg["provider"]["openrouter"]["options"]["apiKey"] == "{env:OPENROUTER_API_KEY}"


def test_build_config_no_provider() -> None:
    cfg_no_provider = AgentConfig.from_slug("opencode", max_turns=5, timeout_s=60)
    cfg = json.loads(_build_config(cfg_no_provider))
    assert "provider" not in cfg
    assert cfg["permission"] == {"*": "allow"}


def test_build_config_anthropic_provider() -> None:
    cfg = AgentConfig.from_slug("opencode:anthropic/claude-opus-4-7", max_turns=5, timeout_s=60)
    result = json.loads(_build_config(cfg))
    assert result["provider"]["anthropic"]["options"]["apiKey"] == "{env:ANTHROPIC_API_KEY}"


# ── _strip_fences ─────────────────────────────────────────────────────────────


def test_strip_fences_no_fences() -> None:
    assert _strip_fences('{"a": 1}') == '{"a": 1}'


def test_strip_fences_json_block() -> None:
    raw = "```json\n{}\n```"
    assert _strip_fences(raw) == "{}"


def test_strip_fences_plain_block() -> None:
    raw = "```\n{}\n```"
    assert _strip_fences(raw) == "{}"


# ── _parse_result ─────────────────────────────────────────────────────────────


def test_parse_result_success() -> None:
    stream = _make_event_stream(
        _text_event(json.dumps(_FULL_SO)),
        _step_finish_event(input_tokens=100, output_tokens=50, cost=0.002),
    )
    result = _parse_result(stream, b"")
    assert result.outcome == "success"
    assert result.summary == "Fixed the bug."
    assert result.actions_taken == ["Edited src/main.py"]
    assert result.items_created == []
    assert result.input_tokens == 100
    assert result.output_tokens == 50
    assert result.total_cost_usd == pytest.approx(0.002)


def test_parse_result_strips_fences() -> None:
    fenced = f"```json\n{json.dumps(_FULL_SO)}\n```"
    stream = _make_event_stream(_text_event(fenced))
    result = _parse_result(stream, b"")
    assert result.outcome == "success"


def test_parse_result_synthetic_text_included_for_extraction() -> None:
    # Synthetic (reasoning) text is now collected; JSON is extracted from the combined text.
    stream = _make_event_stream(
        _text_event("I'll analyse the issue first.", synthetic=True),
        _text_event(json.dumps(_FULL_SO)),
    )
    result = _parse_result(stream, b"")
    assert result.outcome == "success"


def test_parse_result_json_embedded_in_reasoning() -> None:
    # Model emits reasoning prose then JSON — extractor finds the JSON block.
    reasoning = "Let me think about this...\n\nHere is my response:\n"
    stream = _make_event_stream(_text_event(reasoning + json.dumps(_FULL_SO)))
    result = _parse_result(stream, b"")
    assert result.outcome == "success"
    assert result.summary == "Fixed the bug."


def test_parse_result_only_synthetic_containing_json() -> None:
    # All text events are synthetic but contain the JSON — still extracted.
    stream = _make_event_stream(_text_event(json.dumps(_FULL_SO), synthetic=True))
    result = _parse_result(stream, b"")
    assert result.outcome == "success"


def test_parse_result_json_parse_failure() -> None:
    stream = _make_event_stream(_text_event("not valid json at all"))
    result = _parse_result(stream, b"")
    assert result.outcome == "failure"
    assert "json_parse_error" in (result.failure_reason or "")


def test_parse_result_empty_output() -> None:
    result = _parse_result(b"", b"")
    assert result.outcome == "failure"
    assert result.failure_reason is not None


def _error_event(message: str, name: str = "UnknownError") -> dict[str, Any]:
    return {"type": "error", "error": {"name": name, "data": {"message": message}}}


def test_parse_result_error_event_surfaced_as_failure_reason() -> None:
    model_not_found = (
        "Model not found: opencode/nemotron-3-super-free. Did you mean: nemotron-3-ultra-free?"
    )
    stream = _make_event_stream(
        _error_event(model_not_found),
        _error_event("Unexpected server error. Check server logs for details."),
    )
    result = _parse_result(stream, b"")
    assert result.outcome == "failure"
    assert result.failure_reason == model_not_found


def test_parse_result_error_event_preferred_over_json_parse_error() -> None:
    # When both an error event and unparseable text are present, the error message wins.
    stream = _make_event_stream(
        _error_event("Provider rate limit exceeded"),
        _text_event("some garbage output"),
    )
    result = _parse_result(stream, b"")
    assert result.outcome == "failure"
    assert result.failure_reason == "Provider rate limit exceeded"


def test_parse_result_cache_tokens() -> None:
    stream = _make_event_stream(
        _text_event(json.dumps(_FULL_SO)),
        _step_finish_event(cache_read=30, cache_write=10),
    )
    result = _parse_result(stream, b"")
    assert result.cache_read_tokens == 30
    assert result.cache_write_tokens == 10


def test_parse_result_items_created() -> None:
    so = {**_FULL_SO, "items_created": [{"item_type": "pr", "number": 42}]}
    stream = _make_event_stream(_text_event(json.dumps(so)))
    result = _parse_result(stream, b"")
    assert len(result.items_created) == 1
    assert result.items_created[0].item_type == "pr"
    assert result.items_created[0].item_number == 42


def test_parse_result_step_finish_hyphen_variant() -> None:
    """Accept step-finish in the part.type field (top-level type is step_finish)."""
    event = {
        "type": "step-finish",
        "part": {
            "type": "step-finish",
            "tokens": {"input": 7, "output": 3, "cache": {"read": 1, "write": 0}},
            "cost": 0.005,
        },
    }
    stream = _make_event_stream(_text_event(json.dumps(_FULL_SO)), event)
    result = _parse_result(stream, b"")
    assert result.input_tokens == 7
    assert result.total_cost_usd == pytest.approx(0.005)


def test_parse_result_tokens_accumulated_across_steps() -> None:
    """Token counts accumulate across multiple step_finish events."""
    stream = _make_event_stream(
        _step_finish_event(input_tokens=100, output_tokens=50, cost=0.001),
        _text_event(json.dumps(_FULL_SO)),
        _step_finish_event(input_tokens=200, output_tokens=80, cost=0.002),
    )
    result = _parse_result(stream, b"")
    assert result.input_tokens == 300
    assert result.output_tokens == 130
    assert result.total_cost_usd == pytest.approx(0.003)


# ── supports_max_turns ────────────────────────────────────────────────────────


def test_supports_max_turns_false() -> None:
    assert OpenCodeAgent.supports_max_turns is False


def test_invoke_logs_max_turns_ignored(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    config = AgentConfig.from_slug("opencode:openrouter/qwen-3", max_turns=10, timeout_s=5)
    config.cwd = tmp_path
    stream = _make_event_stream(_text_event(json.dumps(_FULL_SO)))

    with patch("labro.agents.opencode._run_subprocess", return_value=(stream, b"")):
        import logging

        with caplog.at_level(logging.DEBUG, logger="labro.agents.opencode"):
            _AGENT.invoke("test prompt", config)

    assert any("max_turns" in r.message and r.levelno == logging.DEBUG for r in caplog.records)


# ── registry integration ──────────────────────────────────────────────────────


def test_opencode_registered() -> None:
    from labro.agents.registry import get_agent

    agent = get_agent("opencode")
    assert agent.id == "opencode"


def test_all_agents_includes_opencode() -> None:
    from labro.agents.registry import all_agents

    ids = {a.id for a in all_agents()}
    assert "opencode" in ids
