"""Agent ABC — contract that every Labro agent implementation must satisfy.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import ClassVar

from labro.models import AgentConfig, AgentResult


class AgentTimeoutError(Exception):
    """Raised when an agent subprocess exceeds its configured timeout."""


class AgentOutputError(Exception):
    """Raised when an agent response cannot be validated."""


class Agent(ABC):
    """Abstract base class for Labro agent implementations."""

    id: ClassVar[str]
    auth_env_vars: ClassVar[tuple[str, ...]]
    supports_max_turns: ClassVar[bool] = True

    @abstractmethod
    def invoke(self, prompt: str, config: AgentConfig) -> AgentResult:
        """Invoke the agent with *prompt* and *config*."""
        ...

    def has_auth(self) -> bool:
        """Return True if any auth credential is present (env vars or local files)."""
        return any(os.environ.get(v) for v in self.auth_env_vars)

    def validate_auth(self) -> tuple[str, str]:
        """Return (status, message) for `labro check`. Status: 'OK  ', 'WARN', 'FAIL'."""
        for var in self.auth_env_vars:
            if os.environ.get(var):
                return ("WARN", f"{var}: env var present but not validated")
        return (
            "FAIL",
            f"no auth for agent '{self.id}' — set one of: {', '.join(self.auth_env_vars)}",
        )
