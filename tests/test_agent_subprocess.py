"""Tests for the shared agent subprocess helper.

@author Claude Opus 5 Anthropic
"""

from __future__ import annotations

import signal
import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from labro.agents import _subprocess
from labro.agents._subprocess import run_cli
from labro.agents.base import AgentTimeoutError


def test_prompt_is_written_to_stdin() -> None:
    """A str prompt reaches the child on stdin."""
    cmd = [sys.executable, "-c", "import sys; sys.stdout.write(sys.stdin.read().upper())"]
    stdout, _stderr, rc = run_cli(cmd, "hello", timeout_s=30)
    assert stdout == b"HELLO"
    assert rc == 0


def test_none_prompt_closes_stdin() -> None:
    """prompt=None gives the child a closed stdin, not a pipe left hanging."""
    cmd = [sys.executable, "-c", "import sys; sys.stdout.write(repr(sys.stdin.read()))"]
    stdout, _stderr, rc = run_cli(cmd, None, timeout_s=30)
    assert stdout == b"''"
    assert rc == 0


def test_stderr_and_returncode_are_returned() -> None:
    cmd = [sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(3)"]
    _stdout, stderr, rc = run_cli(cmd, "", timeout_s=30)
    assert stderr == b"boom"
    assert rc == 3


def test_cwd_is_honoured(tmp_path) -> None:  # type: ignore[no-untyped-def]
    cmd = [sys.executable, "-c", "import os; print(os.getcwd())"]
    stdout, _stderr, _rc = run_cli(cmd, "", timeout_s=30, cwd=tmp_path)
    assert stdout.decode().strip() == str(tmp_path.resolve())


@pytest.mark.parametrize("prompt", ["x", None])
def test_timeout_raises_in_both_stdin_modes(prompt: str | None) -> None:
    cmd = [sys.executable, "-c", "import time; time.sleep(30)"]
    with pytest.raises(AgentTimeoutError):
        run_cli(cmd, prompt, timeout_s=1)


def test_timeout_message_uses_label() -> None:
    cmd = [sys.executable, "-c", "import time; time.sleep(30)"]
    with pytest.raises(AgentTimeoutError, match="opencode exceeded timeout of 1s"):
        run_cli(cmd, None, timeout_s=1, label="opencode")


def test_timeout_message_defaults_to_subprocess() -> None:
    cmd = [sys.executable, "-c", "import time; time.sleep(30)"]
    with pytest.raises(AgentTimeoutError, match="subprocess exceeded timeout of 1s"):
        run_cli(cmd, "x", timeout_s=1)


# ── pgid guard ────────────────────────────────────────────────────────────────
#
# killpg(pgid) is kill(-pgid); kill(-1) signals every process this uid owns.
# A MagicMock pid coerces to 1 via __index__, so a mocked Popen reaching
# _signal_group would SIGKILL the whole login session. These tests must never
# let the real os.killpg run with an untrusted pgid — always stub it.


def _recording_killpg() -> tuple[list[tuple[Any, Any]], Any]:
    calls: list[tuple[Any, Any]] = []
    return calls, lambda pgid, sig: calls.append((pgid, sig))


def test_magicmock_pid_coerces_to_one() -> None:
    """The premise: this is why the guard has to exist."""
    assert MagicMock().pid.__index__() == 1
    assert not isinstance(MagicMock().pid, int)


def test_mocked_popen_never_reaches_killpg() -> None:
    """A mocked Popen must not signal anything — the session-killer regression."""
    calls, recorder = _recording_killpg()
    mock_proc = MagicMock()
    mock_proc.communicate.return_value = (b"out", b"err")
    mock_proc.returncode = 0

    with (
        patch("labro.agents._subprocess.os.killpg", recorder),
        patch("subprocess.Popen", return_value=mock_proc),
    ):
        stdout, stderr, rc = run_cli(["/bin/true"], None, timeout_s=5)

    assert (stdout, stderr, rc) == (b"out", b"err", 0)
    assert calls == [], f"killpg called with a mock pid: {calls}"


@pytest.mark.parametrize("pgid", [1, 0, -1, -5, True])
def test_implausible_pgids_are_refused(pgid: int) -> None:
    """True is an int subclass equal to 1, so killpg(True) is kill(-1)."""
    calls, recorder = _recording_killpg()
    with patch("labro.agents._subprocess.os.killpg", recorder):
        _subprocess._signal_group(pgid, signal.SIGKILL)
    assert calls == []


def test_non_int_pgid_is_refused() -> None:
    calls, recorder = _recording_killpg()
    with patch("labro.agents._subprocess.os.killpg", recorder):
        _subprocess._signal_group(MagicMock().pid, signal.SIGKILL)
    assert calls == []


def test_plausible_pgid_is_signalled() -> None:
    """The guard must not break the real path."""
    calls, recorder = _recording_killpg()
    with patch("labro.agents._subprocess.os.killpg", recorder):
        _subprocess._signal_group(4242, signal.SIGKILL)
    assert calls == [(4242, signal.SIGKILL)]
