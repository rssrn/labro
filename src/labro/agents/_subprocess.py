"""Shared subprocess helper for agent CLI invocations.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from labro.agents.base import AgentTimeoutError


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

    Raises AgentTimeoutError if the process exceeds *timeout_s*.
    """
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE if prompt is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
        shell=False,
    )
    try:
        stdout, stderr = proc.communicate(
            input=prompt.encode() if prompt is not None else None,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise AgentTimeoutError(f"{label} exceeded timeout of {timeout_s}s") from None
    return stdout, stderr, proc.returncode
