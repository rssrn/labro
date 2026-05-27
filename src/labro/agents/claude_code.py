"""Concrete ClaudeCodeAgent implementation.

Delegates subprocess invocation and response parsing to
:mod:`labro.runner`.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

from labro.agents.base import Agent
from labro.models import AgentConfig, AgentResult
from labro.runner import run_claude


class ClaudeCodeAgent(Agent):
    """Agent implementation that invokes the ``claude`` CLI subprocess.

    Uses :func:`~labro.runner.run_claude` to run the agent, validate the
    structured output, and return an :class:`~labro.models.AgentResult`.
    """

    def invoke(self, prompt: str, config: AgentConfig) -> AgentResult:
        """Invoke the ``claude`` CLI with *prompt* and return the result.

        Args:
            prompt: Four-section prompt string from ``prompt_builder``.
            config: Resolved agent invocation parameters.

        Returns:
            Parsed and validated :class:`~labro.models.AgentResult`.
        """
        return run_claude(prompt, config)
