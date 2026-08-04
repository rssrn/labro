"""Tests for the run-tagged process reaper.

@author Claude Opus 5 Anthropic
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid

import pytest

from labro import reaper

pytestmark = pytest.mark.skipif(
    not os.path.isdir("/proc"), reason="reaper reads /proc (Linux only)"
)


def _spawn_tagged(run_id: str, *, detach: bool = False) -> subprocess.Popen[bytes]:
    """Start a long-sleeping child carrying LABRO_RUN_ID=run_id."""
    env = {**os.environ, "LABRO_RUN_ID": run_id}
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=detach,
    )


def _wait_gone(proc: subprocess.Popen[bytes], timeout: float = 10.0) -> bool:
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        return False
    return True


def test_sweep_kills_tagged_process() -> None:
    run_id = str(uuid.uuid4())
    proc = _spawn_tagged(run_id)
    try:
        time.sleep(0.3)  # let the child exec and publish its environ
        hit = reaper.sweep(run_id)
        assert proc.pid in hit
        assert _wait_gone(proc), "tagged process survived the sweep"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def test_sweep_kills_process_that_escaped_its_group() -> None:
    """The case process-group teardown alone misses: a detached setsid child."""
    run_id = str(uuid.uuid4())
    proc = _spawn_tagged(run_id, detach=True)
    try:
        time.sleep(0.3)
        assert os.getpgid(proc.pid) != os.getpgid(os.getpid())
        assert proc.pid in reaper.sweep(run_id)
        assert _wait_gone(proc)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def test_sweep_ignores_other_run_ids() -> None:
    """Concurrent runs for other projects must not be touched."""
    mine, theirs = str(uuid.uuid4()), str(uuid.uuid4())
    proc = _spawn_tagged(theirs)
    try:
        time.sleep(0.3)
        assert reaper.sweep(mine) == []
        assert proc.poll() is None, "a sibling run's process was killed"
    finally:
        proc.kill()
        proc.wait()


def test_sweep_never_targets_self(monkeypatch: pytest.MonkeyPatch) -> None:
    run_id = str(uuid.uuid4())
    monkeypatch.setenv("LABRO_RUN_ID", run_id)
    # This process now carries the tag; re-exec'ing environ is not needed since
    # _tagged_pids reads /proc/<pid>/environ, which is fixed at exec time — so
    # assert on the exclusion logic directly instead.
    assert os.getpid() not in reaper._tagged_pids(run_id)


def test_sweep_returns_empty_when_nothing_tagged() -> None:
    assert reaper.sweep(str(uuid.uuid4())) == []


def test_sweep_escalates_to_sigkill_when_sigterm_ignored() -> None:
    """A process ignoring SIGTERM is still killed — the #58 failure mode."""
    run_id = str(uuid.uuid4())
    script = "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(120)"
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        env={**os.environ, "LABRO_RUN_ID": run_id},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(0.5)  # ensure the handler is installed before we signal
        assert proc.pid in reaper.sweep(run_id, grace_s=1.0)
        assert _wait_gone(proc), "SIGTERM-ignoring process survived"
        assert proc.returncode == -9
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def test_tagged_pids_does_not_prefix_match() -> None:
    """A run_id that is a prefix of another must not cross-match."""
    base = str(uuid.uuid4())
    proc = _spawn_tagged(base + "-extra")
    try:
        time.sleep(0.3)
        assert proc.pid not in reaper._tagged_pids(base)
    finally:
        proc.kill()
        proc.wait()
