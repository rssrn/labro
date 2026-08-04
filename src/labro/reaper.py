"""Run-tagged process reaper.

Every process labro spawns inherits ``LABRO_RUN_ID`` from the environment (set
once per run in ``cli.py``), which makes any survivor attributable to the run
that created it — orphans reparent to PID 1 and are otherwise untraceable.
``sweep`` finds those survivors and kills them.

This is the backstop for the process-group teardown in ``agents/_subprocess``:
a grandchild that calls ``setsid`` escapes its process group, but it cannot
shed the inherited environment.

Linux-only (reads ``/proc``); degrades to a no-op elsewhere.

@author Claude Opus 5 Anthropic
"""

from __future__ import annotations

import logging
import os
import signal
import time
from pathlib import Path

_log = logging.getLogger(__name__)

_PROC = Path("/proc")

# Seconds between SIGTERM and SIGKILL for strays that ignore the first signal.
_GRACE_S = 3.0


def _tagged_pids(run_id: str) -> list[int]:
    """Return pids whose environment carries ``LABRO_RUN_ID=run_id``.

    Excludes this process, which necessarily carries the same tag.
    """
    if not _PROC.is_dir():
        return []

    needle = f"LABRO_RUN_ID={run_id}".encode()
    self_pid = os.getpid()
    found: list[int] = []

    for entry in _PROC.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid == self_pid:
            continue
        try:
            environ = (entry / "environ").read_bytes()
        except (OSError, ValueError):
            # Process exited mid-scan, or we lack permission to read it.
            continue
        # environ is NUL-separated; match a whole entry so a run_id that is a
        # prefix of another cannot cross-match.
        if needle in environ.split(b"\0"):
            found.append(pid)

    return found


def _alive(pid: int) -> bool:
    """True if *pid* exists and is not a zombie awaiting reaping."""
    try:
        stat = (_PROC / str(pid) / "stat").read_bytes()
    except OSError:
        return False
    # Field 3 is the state character, after the comm field's closing paren.
    # comm can itself contain parens, so split on the *last* one.
    _, _, rest = stat.rpartition(b")")
    fields = rest.split()
    return bool(fields) and fields[0] != b"Z"


def _signal(pid: int, sig: signal.Signals) -> None:
    """Send *sig* to *pid*, ignoring races and permission failures."""
    try:
        os.kill(pid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def sweep(run_id: str, grace_s: float = _GRACE_S) -> list[int]:
    """Kill every surviving process tagged with *run_id*; return the pids hit.

    SIGTERM first, then SIGKILL for anything still alive after *grace_s* — a
    process wedged in a synchronous compute loop never services SIGTERM, which
    is precisely how the incident in #58 stayed alive for 36 minutes.

    Only ever targets *this* run's tag. Runs for different projects execute
    concurrently under separate locks, so sweeping other run_ids would kill a
    live sibling run's agent.
    """
    pids = _tagged_pids(run_id)
    if not pids:
        return []

    _log.warning("reaping %d stray process(es) from run %s: %s", len(pids), run_id[:8], pids)
    for pid in pids:
        _signal(pid, signal.SIGTERM)

    deadline = time.monotonic() + grace_s
    while time.monotonic() < deadline:
        if not any(_alive(pid) for pid in pids):
            return pids
        time.sleep(0.1)

    for pid in pids:
        if _alive(pid):
            _log.warning("stray pid %d ignored SIGTERM; sending SIGKILL", pid)
            _signal(pid, signal.SIGKILL)

    return pids
