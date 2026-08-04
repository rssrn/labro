"""Process-group teardown tests for the agent subprocess helper.

Covers the #58 failure mode: an agent spawns a tool subprocess, the agent is
killed, and the grandchild keeps running on the host.

@author Claude Opus 5 Anthropic
"""

from __future__ import annotations

import contextlib
import os
import signal
import sys
import time

import pytest

from labro.agents._subprocess import run_cli
from labro.agents.base import AgentTimeoutError

pytestmark = pytest.mark.skipif(
    not os.path.isdir("/proc"), reason="teardown assertions read /proc (Linux only)"
)

# Spawns a grandchild that outlives it, records the pid, then hangs.
# The grandchild inherits stdout/stderr, which is what makes a naive
# post-kill communicate() block forever.
_SPAWNER = """
import subprocess, sys, time
gc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
open(sys.argv[1], "w").write(str(gc.pid))
sys.stdout.flush()
time.sleep(120)
"""

# Same, but the grandchild detaches into its own session first.
_SPAWNER_DETACHED = """
import subprocess, sys, time
gc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"],
                      start_new_session=True)
open(sys.argv[1], "w").write(str(gc.pid))
sys.stdout.flush()
time.sleep(120)
"""


def _read_pid(path, timeout: float = 10.0) -> int:  # type: ignore[no-untyped-def]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists() and path.read_text().strip():
            return int(path.read_text().strip())
        time.sleep(0.05)
    raise AssertionError("grandchild never reported its pid")


def _gone(pid: int, timeout: float = 10.0) -> bool:
    """True once *pid* is dead or a zombie awaiting reaping."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            stat = open(f"/proc/{pid}/stat", "rb").read()
        except OSError:
            return True
        _, _, rest = stat.rpartition(b")")
        if rest.split() and rest.split()[0] == b"Z":
            return True
        time.sleep(0.05)
    return False


def _cleanup(pid: int) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.kill(pid, signal.SIGKILL)


def test_child_gets_its_own_process_group() -> None:
    cmd = [sys.executable, "-c", "import os; print(os.getpgid(0) == os.getpid())"]
    stdout, _stderr, _rc = run_cli(cmd, None, timeout_s=30)
    assert stdout.strip() == b"True"


def test_timeout_kills_grandchild(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """The core #58 regression: grandchild must not outlive the timeout."""
    pidfile = tmp_path / "gc.pid"
    cmd = [sys.executable, "-c", _SPAWNER, str(pidfile)]

    start = time.monotonic()
    with pytest.raises(AgentTimeoutError):
        run_cli(cmd, None, timeout_s=2, label="spawner")
    elapsed = time.monotonic() - start

    gc_pid = _read_pid(pidfile)
    try:
        assert _gone(gc_pid), f"grandchild {gc_pid} survived the timeout teardown"
        # Must not have blocked draining pipes the grandchild held.
        assert elapsed < 20, f"teardown took {elapsed:.1f}s — drain was unbounded"
    finally:
        _cleanup(gc_pid)


def test_normal_exit_kills_leftover_grandchild(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Leaks are not timeout-specific: an agent exiting 0 can leave strays too."""
    pidfile = tmp_path / "gc.pid"
    # Parent spawns a detached grandchild, then exits cleanly and immediately.
    script = (
        "import subprocess, sys\n"
        "gc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'],\n"
        "                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        "open(sys.argv[1], 'w').write(str(gc.pid))\n"
    )
    cmd = [sys.executable, "-c", script, str(pidfile)]

    _stdout, _stderr, rc = run_cli(cmd, None, timeout_s=30)
    assert rc == 0

    gc_pid = _read_pid(pidfile)
    try:
        assert _gone(gc_pid), f"grandchild {gc_pid} survived a successful run"
    finally:
        _cleanup(gc_pid)


def test_timeout_does_not_hang_on_detached_grandchild(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """A setsid grandchild escapes the group; teardown must still not block.

    The reaper sweep is what actually kills this one, so we only assert that
    run_cli returns promptly rather than wedging on the inherited pipes.
    """
    pidfile = tmp_path / "gc.pid"
    cmd = [sys.executable, "-c", _SPAWNER_DETACHED, str(pidfile)]

    start = time.monotonic()
    with pytest.raises(AgentTimeoutError):
        run_cli(cmd, None, timeout_s=2, label="spawner")
    elapsed = time.monotonic() - start

    gc_pid = _read_pid(pidfile)
    try:
        assert elapsed < 20, f"teardown took {elapsed:.1f}s — drain was unbounded"
    finally:
        _cleanup(gc_pid)
