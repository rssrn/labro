"""Tests for the shared agent subprocess helper.

@author Claude Opus 5 Anthropic
"""

from __future__ import annotations

import sys

import pytest

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
