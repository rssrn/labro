"""Tests for labro.agents.codex — parse_result error paths and success path.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import json
import subprocess
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from labro.agents.base import AgentOutputError, AgentTimeoutError
from labro.agents.codex import CodexAgent
from labro.models import AgentConfig

_BASE_CONFIG = AgentConfig.from_slug(
    "codex:openai/o4-mini",
    max_turns=5,
    timeout_s=120,
)

_AGENT = CodexAgent()

_FULL_SO: dict[str, Any] = {
    "outcome": "success",
    "summary": "Done.",
    "actions_taken": [],
    "items_created": [],
    "failure_reason": None,
}


def _make_turn_completed(
    input_tokens: int = 10,
    output_tokens: int = 20,
    cached: int = 5,
) -> bytes:
    return json.dumps(
        {
            "type": "turn.completed",
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cached_input_tokens": cached,
            },
        }
    ).encode()


def _call_parse_result(
    agent: CodexAgent,
    stdout: bytes,
    stderr: bytes,
    rc: int,
    out_path: str,
) -> Any:
    """Call the private _parse_result directly to avoid tempfile/subprocess setup."""
    return agent._parse_result(stdout, stderr, rc, out_path)


# ── infrastructure failure paths (should raise AgentOutputError) ──────────────


def test_nonzero_exit_raises(tmp_path: pytest.TempPathFactory) -> None:
    with pytest.raises(AgentOutputError, match="exit_code_1"):
        _call_parse_result(
            _AGENT,
            stdout=b"",
            stderr=b"codex: model not found",
            rc=1,
            out_path=str(tmp_path / "out.json"),  # type: ignore[operator]
        )


def test_error_event_raises(tmp_path: pytest.TempPathFactory) -> None:
    error_line = json.dumps(
        {"type": "turn.failed", "message": "Model not available: openai/no-such-model"}
    ).encode()
    with pytest.raises(AgentOutputError, match="Model not available"):
        _call_parse_result(
            _AGENT,
            stdout=error_line,
            stderr=b"",
            rc=0,
            out_path=str(tmp_path / "out.json"),  # type: ignore[operator]
        )


def test_missing_output_file_raises(tmp_path: pytest.TempPathFactory) -> None:
    """rc=0 but output file absent → AgentOutputError."""
    with pytest.raises(AgentOutputError, match="exit_code_0"):
        _call_parse_result(
            _AGENT,
            stdout=_make_turn_completed(),
            stderr=b"",
            rc=0,
            out_path=str(tmp_path / "out.json"),  # type: ignore[operator]
        )


# ── quota exceeded ───────────────────────────────────────────────────────────


def test_quota_exceeded_returns_session_limit_hit(tmp_path: pytest.TempPathFactory) -> None:
    stderr = (
        b"OpenAI Codex v0.139.0\nERROR: Quota exceeded. Check your plan and billing details.\n"
    )
    result = _call_parse_result(
        _AGENT,
        stdout=b"",
        stderr=stderr,
        rc=1,
        out_path=str(tmp_path / "out.json"),  # type: ignore[operator]
    )
    assert result.outcome == "failure"
    assert result.failure_reason == "session_limit_hit"


# ── success path ──────────────────────────────────────────────────────────────


def test_success_returns_result(tmp_path: pytest.TempPathFactory) -> None:
    out_file = tmp_path / "out.json"  # type: ignore[operator]
    out_file.write_text(json.dumps(_FULL_SO))

    result = _call_parse_result(
        _AGENT,
        stdout=_make_turn_completed(10, 20, 5),
        stderr=b"",
        rc=0,
        out_path=str(out_file),
    )

    assert result.outcome == "success"
    assert result.input_tokens == 10
    assert result.output_tokens == 20
    assert result.cache_read_tokens == 5


# ── timeout ───────────────────────────────────────────────────────────────────


def test_timeout_raises_agent_timeout_error(tmp_path: pytest.TempPathFactory) -> None:
    mock = MagicMock()
    mock.communicate.side_effect = [
        subprocess.TimeoutExpired(cmd="codex", timeout=120),
        (b"", b""),
    ]
    mock.kill = MagicMock()

    with (
        patch("subprocess.Popen", return_value=mock),
        patch("labro.agents.codex.CodexAgent.invoke") as mock_invoke,
    ):
        mock_invoke.side_effect = AgentTimeoutError("codex exceeded timeout of 120s")
        with pytest.raises(AgentTimeoutError):
            _AGENT.invoke("prompt", _BASE_CONFIG)


# ── validate_auth / binary check ──────────────────────────────────────────────


def test_validate_auth_fails_when_binary_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """validate_auth returns FAIL when the codex binary is not on PATH."""
    monkeypatch.setenv("CODEX_API_KEY", "key")
    with patch("shutil.which", return_value=None):
        status, msg = _AGENT.validate_auth()
    assert status == "FAIL"
    assert "codex" in msg
    assert "PATH" in msg


def test_validate_auth_ok_when_binary_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """validate_auth proceeds past the binary check when codex is on PATH."""
    monkeypatch.setenv("CODEX_API_KEY", "key")
    with patch("shutil.which", return_value="/usr/bin/codex"):
        status, _ = _AGENT.validate_auth()
    assert status != "FAIL"
