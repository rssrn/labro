"""Shared subprocess helper for agent CLI invocations.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
from pathlib import Path

from labro.agents.base import AgentTimeoutError

_log = logging.getLogger(__name__)

# Seconds to wait for a process group to honour SIGTERM before SIGKILL.
_TERM_GRACE_S = 5.0

# Bound on draining stdout/stderr after killing the group, so a process that
# escaped the group while holding an inherited pipe fd cannot wedge the harness.
_DRAIN_TIMEOUT_S = 5.0


def run_cli(
    cmd: list[str],
    prompt: str | None,
    timeout_s: int,
    cwd: Path | None = None,
    label: str = "subprocess",
) -> tuple[bytes, bytes, int]:
    """Run *cmd* and return (stdout, stderr, returncode).

    *prompt* is written to stdin; pass None for agents that take the prompt as
    an argv argument instead, which gets the child a closed stdin rather than a
    pipe nobody writes to. *label* names the process in the timeout message.

    The child gets its own session and process group, and the whole group is
    torn down on the way out — on timeout *and* on normal exit. Agents spawn
    tool subprocesses that can outlive them; signalling only the direct child
    leaves those running on the host indefinitely (see #58).

    Raises AgentTimeoutError if the process exceeds *timeout_s*.
    """
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE if prompt is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
        shell=False,
        start_new_session=True,
    )
    # start_new_session=True calls setsid(), which makes the child leader of a
    # new process group whose id equals its pid.
    pgid = proc.pid
    try:
        try:
            stdout, stderr = proc.communicate(
                input=prompt.encode() if prompt is not None else None,
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            _terminate_group(proc, pgid, label)
            raise AgentTimeoutError(f"{label} exceeded timeout of {timeout_s}s") from None
    finally:
        # Unconditional: an agent that exits 0 can still leave behind whatever
        # it backgrounded. Anything left in the group at this point is by
        # definition an orphan, since the agent itself has exited.
        _signal_group(pgid, signal.SIGKILL)
    return stdout, stderr, proc.returncode


def _signal_group(pgid: int, sig: signal.Signals) -> None:
    """Send *sig* to process group *pgid*, ignoring an already-empty group."""
    # killpg(pgid) is kill(-pgid), and kill(-1) means "every process this uid may
    # signal" — so pgid 1 wipes out the whole login session. POSIX calls pgid <= 1
    # undefined. A MagicMock pid from a mocked Popen coerces to exactly 1 via
    # __index__, which turned a unit test into a session killer.
    # bool is excluded explicitly: it is an int subclass, and killpg(True) is
    # killpg(1) is kill(-1) — precisely the catastrophe being guarded against.
    if not isinstance(pgid, int) or isinstance(pgid, bool) or pgid <= 1:
        _log.error("refusing to signal implausible pgid %r", pgid)
        return
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):
        pass
    except OSError as exc:  # pragma: no cover - platform-dependent
        _log.warning("could not signal process group %d: %s", pgid, exc)


def _terminate_group(proc: subprocess.Popen[bytes], pgid: int, label: str) -> None:
    """Escalate SIGTERM -> SIGKILL across the group, then drain the pipes."""
    _signal_group(pgid, signal.SIGTERM)
    try:
        proc.wait(timeout=_TERM_GRACE_S)
    except subprocess.TimeoutExpired:
        _log.warning("%s ignored SIGTERM after timeout; escalating to SIGKILL", label)
    _signal_group(pgid, signal.SIGKILL)

    try:
        proc.communicate(timeout=_DRAIN_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        # Something outside the group still holds the pipes. Drop them rather
        # than block; the reaper sweep at run end is the remaining backstop.
        _log.warning("%s pipes still held after SIGKILL; abandoning drain", label)
        for stream in (proc.stdin, proc.stdout, proc.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
