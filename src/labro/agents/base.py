"""Agent ABC -- defines the contract that every Labro agent implementation must satisfy.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from labro.models import AgentConfig, AgentResult


class Agent(ABC):
    """Abstract base class for Labro agent implementations.

    Concrete implementations (e.g. ``ClaudeCodeAgent`` in M2) must override
    ``invoke`` to run the agent subprocess and return a structured result.
    """

    @abstractmethod
    def invoke(self, prompt: str, config: AgentConfig) -> AgentResult:
        """Invoke the agent with *prompt* and *config*.

        Args:
            prompt: The four-section prompt string produced by ``prompt_builder``.
            config: Resolved agent invocation parameters (model, max_turns, ...).

        Returns:
            An ``AgentResult`` describing the outcome.
        """
        ...
