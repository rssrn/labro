"""Tests for labro.runner — structured_output validation and error paths.

Integration tests (test_hello_world, test_structured_output_shape) require
the ``claude`` CLI to be in PATH and a valid CLAUDE_CODE_OAUTH_TOKEN /
ANTHROPIC_API_KEY env var to be set.  They are skipped automatically when
the CLI is absent so the unit tests still run in plain Python environments.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from labro.config.schema import PermittedAction
from labro.models import AgentConfig, AgentResult, ItemRef
from labro.runner import (
    _BASE_TOOLS,
    RunnerOutputError,
    RunnerTimeoutError,
    _build_allowed_tools,
    run_claude,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CLAUDE_AVAILABLE = shutil.which("claude") is not None

_BASE_CONFIG = AgentConfig.from_slug(
    "claude-code:anthropic/claude-haiku-4-5-20251001",
    max_turns=3,
    timeout_s=120,
)


def _check_claude_functional() -> bool:
    if not CLAUDE_AVAILABLE:
        return False
    try:
        run_claude(
            "Reply only with valid JSON matching the schema — set outcome='success', "
            "summary='probe', actions_taken=[], items_created=[].",
            _BASE_CONFIG,
        )
        return True
    except Exception:
        return False


CLAUDE_FUNCTIONAL = _check_claude_functional()


def _make_response(
    *,
    subtype: str = "success",
    is_error: bool = False,
    num_turns: int = 1,
    total_cost_usd: float = 0.001,
    duration_ms: int = 500,
    structured_output: dict[str, Any] | None = None,
) -> bytes:
    """Build a minimal fake claude CLI JSON response."""
    if structured_output is None:
        structured_output = {
            "outcome": "success",
            "summary": "Did the thing.",
            "actions_taken": [],
            "items_created": [],
            "failure_reason": None,
        }
    payload: dict[str, Any] = {
        "type": "result",
        "subtype": subtype,
        "is_error": is_error,
        "num_turns": num_turns,
        "total_cost_usd": total_cost_usd,
        "duration_ms": duration_ms,
        "result": "",
        "usage": {
            "input_tokens": 10,
            "output_tokens": 20,
            "cache_read_input_tokens": 5,
            "cache_creation_input_tokens": 3,
        },
        "structured_output": structured_output,
    }
    return json.dumps(payload).encode()


def _mock_popen(stdout: bytes, *, returncode: int = 0) -> MagicMock:
    """Return a mock Popen instance whose ``communicate`` returns *stdout*."""
    mock_proc = MagicMock()
    mock_proc.communicate.return_value = (stdout, b"")
    mock_proc.returncode = returncode
    return mock_proc


# ---------------------------------------------------------------------------
# Integration tests — skipped when claude CLI is unavailable
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not CLAUDE_FUNCTIONAL,
    reason="claude CLI not in PATH or not functional (e.g. out of quota/unauthenticated)",
)
def test_hello_world() -> None:
    """Invoke claude with a trivial prompt; assert top-level fields present."""
    config = AgentConfig.from_slug(
        "claude-code:anthropic/claude-haiku-4-5-20251001",
        max_turns=3,
        timeout_s=120,
    )
    result = run_claude(
        "Reply only with valid JSON matching the schema — set outcome='success', "
        "summary='hello world', actions_taken=[], items_created=[].",
        config,
    )
    assert isinstance(result, AgentResult)
    assert isinstance(result.is_error, bool)
    assert isinstance(result.num_turns, int)
    assert isinstance(result.total_cost_usd, float)


@pytest.mark.skipif(
    not CLAUDE_FUNCTIONAL,
    reason="claude CLI not in PATH or not functional (e.g. out of quota/unauthenticated)",
)
def test_structured_output_shape() -> None:
    """Assert structured_output fields conform to the ARCHITECTURE §11 schema."""
    config = AgentConfig.from_slug(
        "claude-code:anthropic/claude-haiku-4-5-20251001",
        max_turns=3,
        timeout_s=120,
    )
    result = run_claude(
        "Reply only with valid JSON matching the schema — set outcome='success', "
        "summary='shape test', actions_taken=['echo hi'], items_created=[].",
        config,
    )
    assert result.outcome in {"success", "failure", "partial"}
    assert isinstance(result.actions_taken, list)
    assert isinstance(result.items_created, list)
    assert all(isinstance(r, ItemRef) for r in result.items_created)


# ---------------------------------------------------------------------------
# Unit tests — mock subprocess.Popen
# ---------------------------------------------------------------------------


def test_missing_structured_output_returns_failure() -> None:
    """Response without 'structured_output' key returns AgentResult(outcome='failure')."""
    payload = json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "num_turns": 1,
            "total_cost_usd": 0.005,
            "duration_ms": 100,
            "result": "some last message",
            "usage": {"input_tokens": 10, "output_tokens": 5},
            # structured_output deliberately absent
        }
    ).encode()

    with patch("subprocess.Popen") as mock_popen_cls:
        mock_popen_cls.return_value = _mock_popen(payload)
        result = run_claude("prompt", _BASE_CONFIG)

    assert result.outcome == "failure"
    assert result.total_cost_usd == pytest.approx(0.005)
    assert result.summary == "some last message"


def test_structured_output_none_returns_failure() -> None:
    """Response with structured_output=null returns AgentResult(outcome='failure')."""
    payload = json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "num_turns": 1,
            "total_cost_usd": 0.003,
            "duration_ms": 100,
            "result": "",
            "usage": {},
            "structured_output": None,
        }
    ).encode()

    with patch("subprocess.Popen") as mock_popen_cls:
        mock_popen_cls.return_value = _mock_popen(payload)
        result = run_claude("prompt", _BASE_CONFIG)

    assert result.outcome == "failure"
    assert result.total_cost_usd == pytest.approx(0.003)


def test_error_max_turns_returns_partial() -> None:
    """error_max_turns with no structured_output returns AgentResult(outcome='partial')."""
    payload = json.dumps(
        {
            "type": "result",
            "subtype": "error_max_turns",
            "is_error": True,
            "num_turns": 5,
            "total_cost_usd": 0.012,
            "duration_ms": 3000,
            "result": "Completed steps 1-3 of 5.",
            "usage": {
                "input_tokens": 100,
                "output_tokens": 50,
                "cache_read_input_tokens": 20,
                "cache_creation_input_tokens": 10,
            },
            # structured_output absent — turn limit hit before agent could fill it
        }
    ).encode()

    with patch("subprocess.Popen") as mock_popen_cls:
        mock_popen_cls.return_value = _mock_popen(payload)
        result = run_claude("prompt", _BASE_CONFIG)

    assert result.outcome == "partial"
    assert result.summary == "Completed steps 1-3 of 5."
    assert result.failure_reason == "error_max_turns"
    assert result.total_cost_usd == pytest.approx(0.012)
    assert result.num_turns == 5
    assert result.input_tokens == 100
    assert result.output_tokens == 50
    assert result.cache_read_tokens == 20
    assert result.cache_write_tokens == 10


def test_session_limit_hit_returns_failure_with_slug() -> None:
    """Session-limit response (is_error=True, subtype='success') maps to session_limit_hit slug."""
    payload = json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": True,
            "num_turns": 1,
            "total_cost_usd": 0.0,
            "duration_ms": 200,
            "result": "You've hit your session limit · resets 9:40am (UTC)",
            "usage": {
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
            },
        }
    ).encode()

    with patch("subprocess.Popen") as mock_popen_cls:
        mock_popen_cls.return_value = _mock_popen(payload)
        result = run_claude("prompt", _BASE_CONFIG)

    assert result.outcome == "failure"
    assert result.failure_reason == "session_limit_hit"
    assert "session limit" in result.summary.lower()


def test_session_limit_mid_run_preserves_token_counts() -> None:
    """Session limit hit after partial work: token counts are captured."""
    payload = json.dumps(
        {
            "type": "result",
            "subtype": "success",
            "is_error": True,
            "num_turns": 3,
            "total_cost_usd": 0.091,
            "duration_ms": 5000,
            "result": "You've hit your session limit · resets 9:40am (UTC)",
            "usage": {
                "input_tokens": 3,
                "output_tokens": 232,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 22520,
            },
        }
    ).encode()

    with patch("subprocess.Popen") as mock_popen_cls:
        mock_popen_cls.return_value = _mock_popen(payload)
        result = run_claude("prompt", _BASE_CONFIG)

    assert result.failure_reason == "session_limit_hit"
    assert result.output_tokens == 232
    assert result.cache_write_tokens == 22520
    assert result.total_cost_usd == pytest.approx(0.091)


def test_missing_so_non_max_turns_returns_failure() -> None:
    """Non-max-turns subtype with no structured_output returns outcome='failure'."""
    payload = json.dumps(
        {
            "type": "result",
            "subtype": "error_other",
            "is_error": True,
            "num_turns": 2,
            "total_cost_usd": 0.007,
            "duration_ms": 500,
            "result": "",
            "usage": {},
        }
    ).encode()

    with patch("subprocess.Popen") as mock_popen_cls:
        mock_popen_cls.return_value = _mock_popen(payload)
        result = run_claude("prompt", _BASE_CONFIG)

    assert result.outcome == "failure"
    assert result.failure_reason == "error_other"
    assert result.total_cost_usd == pytest.approx(0.007)


def test_malformed_structured_output_still_raises() -> None:
    """A present-but-malformed structured_output still raises RunnerOutputError."""
    bad_so = {
        "outcome": "bad_value",
        "summary": "x",
        "actions_taken": [],
        "items_created": [],
    }
    with patch("subprocess.Popen") as mock_popen_cls:
        mock_popen_cls.return_value = _mock_popen(_make_response(structured_output=bad_so))
        with pytest.raises(RunnerOutputError, match="outcome"):
            run_claude("prompt", _BASE_CONFIG)


def test_agent_partial_preserved_when_cli_success() -> None:
    """Agent-reported 'partial' in a successful CLI response is kept as 'partial'."""
    so = {
        "outcome": "partial",
        "summary": "Did half the work.",
        "actions_taken": [],
        "items_created": [],
    }
    with patch("subprocess.Popen") as mock_popen_cls:
        mock_popen_cls.return_value = _mock_popen(
            _make_response(subtype="success", is_error=False, structured_output=so)
        )
        result = run_claude("prompt", _BASE_CONFIG)

    assert result.outcome == "partial"


def test_malformed_outcome_raises() -> None:
    """structured_output.outcome with an invalid value must raise RunnerOutputError."""
    bad_so = {
        "outcome": "oops",
        "summary": "Something happened.",
        "actions_taken": [],
        "items_created": [],
    }
    with patch("subprocess.Popen") as mock_popen_cls:
        mock_popen_cls.return_value = _mock_popen(_make_response(structured_output=bad_so))
        with pytest.raises(RunnerOutputError, match="outcome"):
            run_claude("prompt", _BASE_CONFIG)


def test_empty_summary_raises() -> None:
    """structured_output.summary that is empty must raise RunnerOutputError."""
    bad_so = {
        "outcome": "success",
        "summary": "   ",
        "actions_taken": [],
        "items_created": [],
    }
    with patch("subprocess.Popen") as mock_popen_cls:
        mock_popen_cls.return_value = _mock_popen(_make_response(structured_output=bad_so))
        with pytest.raises(RunnerOutputError, match="summary"):
            run_claude("prompt", _BASE_CONFIG)


def test_items_created_bad_item_type_raises() -> None:
    """items_created with unknown item_type must raise RunnerOutputError."""
    bad_so = {
        "outcome": "success",
        "summary": "done",
        "actions_taken": [],
        "items_created": [{"item_type": "commit", "number": 1}],
    }
    with patch("subprocess.Popen") as mock_popen_cls:
        mock_popen_cls.return_value = _mock_popen(_make_response(structured_output=bad_so))
        with pytest.raises(RunnerOutputError, match="item_type"):
            run_claude("prompt", _BASE_CONFIG)


def test_timeout_raises() -> None:
    """Subprocess timeout must raise RunnerTimeoutError and kill the process."""
    mock_proc = MagicMock()
    # First call (with timeout kwarg) raises; second call (drain) returns empty bytes.
    mock_proc.communicate.side_effect = [
        subprocess.TimeoutExpired(cmd="claude", timeout=0),
        (b"", b""),  # drain call after kill
    ]

    with patch("subprocess.Popen", return_value=mock_proc):
        with pytest.raises(RunnerTimeoutError):
            run_claude("prompt", _BASE_CONFIG)

    mock_proc.kill.assert_called_once()


def test_successful_run_returns_agent_result() -> None:
    """A well-formed response returns a correctly populated AgentResult."""
    so = {
        "outcome": "success",
        "summary": "Opened PR #99.",
        "actions_taken": ["gh pr create"],
        "items_created": [{"item_type": "pr", "number": 99}],
        "failure_reason": None,
    }
    with patch("subprocess.Popen") as mock_popen_cls:
        mock_popen_cls.return_value = _mock_popen(
            _make_response(
                structured_output=so,
                num_turns=2,
                total_cost_usd=0.005,
                duration_ms=1234,
            )
        )
        result = run_claude("prompt", _BASE_CONFIG)

    assert result.outcome == "success"
    assert result.summary == "Opened PR #99."
    assert result.actions_taken == ["gh pr create"]
    assert len(result.items_created) == 1
    assert result.items_created[0].item_type == "pr"
    assert result.items_created[0].item_number == 99
    assert result.num_turns == 2
    assert result.total_cost_usd == pytest.approx(0.005)
    assert result.duration_ms == 1234
    assert result.input_tokens == 10
    assert result.output_tokens == 20
    assert result.cache_read_tokens == 5
    assert result.cache_write_tokens == 3


def test_is_error_true_overrides_outcome_to_failure() -> None:
    """is_error=True must force outcome to 'failure' regardless of structured_output.outcome."""
    so = {
        "outcome": "success",
        "summary": "It looked fine but it wasn't.",
        "actions_taken": [],
        "items_created": [],
    }
    with patch("subprocess.Popen") as mock_popen_cls:
        mock_popen_cls.return_value = _mock_popen(
            _make_response(is_error=True, structured_output=so)
        )
        result = run_claude("prompt", _BASE_CONFIG)

    assert result.outcome == "failure"
    assert result.is_error is True


def test_subtype_not_success_downgrades_success_to_failure() -> None:
    """subtype != 'success' downgrades a structured_output outcome of 'success' to 'failure'."""
    so = {
        "outcome": "success",
        "summary": "Partial run.",
        "actions_taken": [],
        "items_created": [],
    }
    with patch("subprocess.Popen") as mock_popen_cls:
        mock_popen_cls.return_value = _mock_popen(
            _make_response(subtype="error", structured_output=so)
        )
        result = run_claude("prompt", _BASE_CONFIG)

    assert result.outcome == "failure"


def test_malformed_json_raises() -> None:
    """Non-JSON stdout must raise RunnerOutputError."""
    with patch("subprocess.Popen") as mock_popen_cls:
        mock_popen_cls.return_value = _mock_popen(b"not valid json")
        with pytest.raises(RunnerOutputError, match="parse"):
            run_claude("prompt", _BASE_CONFIG)


def test_shell_false_enforced() -> None:
    """Popen must always be called with shell=False (default; no shell=True)."""
    with patch("subprocess.Popen") as mock_popen_cls:
        mock_popen_cls.return_value = _mock_popen(_make_response())
        run_claude("prompt", _BASE_CONFIG)

    _, kwargs = mock_popen_cls.call_args
    assert kwargs.get("shell", False) is False


# ---------------------------------------------------------------------------
# _build_allowed_tools
# ---------------------------------------------------------------------------


def test_build_allowed_tools_empty_returns_base() -> None:
    """No permitted actions → only the read-only baseline tools."""
    tools = _build_allowed_tools([])
    assert tools == _BASE_TOOLS


def test_build_allowed_tools_comment_on_issue() -> None:
    tools = _build_allowed_tools([PermittedAction.COMMENT_ON_ISSUE])
    assert "Bash(gh issue comment *)" in tools
    # Baseline still present
    assert "Read" in tools


def test_build_allowed_tools_no_cross_contamination() -> None:
    """comment_on_issue must not grant pr-merge patterns."""
    tools = _build_allowed_tools([PermittedAction.COMMENT_ON_ISSUE])
    assert "Bash(gh pr merge *)" not in tools


def test_build_allowed_tools_all_actions_covered() -> None:
    """Every PermittedAction maps to at least one tool pattern."""
    all_tools = _build_allowed_tools(list(PermittedAction))
    # Spot-check one pattern per action
    expected = [
        "Bash(gh issue comment *)",
        "Bash(gh pr comment *)",
        "Bash(gh pr create *)",
        "Bash(gh pr merge *)",
        "Bash(git push *)",
        "Bash(gh issue close *)",
        "Bash(gh issue create *)",
    ]
    for pattern in expected:
        assert pattern in all_tools, f"missing: {pattern}"


def test_allowed_tools_passed_to_subprocess() -> None:
    """run_claude must forward --allowedTools to the claude subprocess."""
    config = AgentConfig.from_slug(
        "claude-code:anthropic/claude-haiku-4-5-20251001",
        max_turns=3,
        timeout_s=120,
        permitted_actions=[PermittedAction.COMMENT_ON_ISSUE],
    )
    with patch("subprocess.Popen") as mock_popen_cls:
        mock_popen_cls.return_value = _mock_popen(_make_response())
        run_claude("prompt", config)

    args, _ = mock_popen_cls.call_args
    cmd: list[str] = args[0]
    assert "--allowedTools" in cmd
    idx = cmd.index("--allowedTools")
    tools_passed = cmd[idx + 1 :]
    assert "Bash(gh issue comment *)" in tools_passed
