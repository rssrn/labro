"""Shared subprocess helper for agent CLI invocations.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from labro.agents.base import AgentTimeoutError


def run_cli(
    cmd: list[str],
    prompt: str,
    timeout_s: int,
    cwd: Path | None = None,
) -> tuple[bytes, bytes, int]:
    """Run *cmd* with *prompt* on stdin and return (stdout, stderr, returncode).

    Raises AgentTimeoutError if the process exceeds *timeout_s*.
    """
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
        shell=False,
    )
    try:
        stdout, stderr = proc.communicate(input=prompt.encode(), timeout=timeout_s)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise AgentTimeoutError(f"subprocess exceeded timeout of {timeout_s}s") from None
    return stdout, stderr, proc.returncode
