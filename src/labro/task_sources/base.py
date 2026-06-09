"""TaskSource abstract base class.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from labro.config.schema import ProjectConfig
from labro.models import AgentConfig, Task


class TaskSource(ABC):
    """Abstract base for all task sources.

    Implementations are responsible for fetching one candidate task from their
    backing system and resolving all config overrides (label_rule → source →
    project → defaults) before returning.  The returned Task carries only
    resolved values — the picker and prompt builder treat all task sources
    uniformly.
    """

    @abstractmethod
    def fetch_task(
        self,
        project: ProjectConfig,
        defaults_model: list[str],
        defaults_max_turns: int,
        defaults_timeout_s: int,
        defaults_max_comments: int,
    ) -> tuple[Task, AgentConfig] | None:
        """Return a ``(Task, AgentConfig)`` pair if a task is available, else ``None``.

        Args:
            project: The project configuration for this fetch.
            defaults_model: Global ``[defaults].model`` fallback (list of slug strings).
            defaults_max_turns: Global ``[defaults].max_turns`` fallback.
            defaults_timeout_s: Global ``[defaults].timeout_s`` fallback.
            defaults_max_comments: Global ``[defaults].max_comments`` fallback.

        Returns:
            A ``(Task, AgentConfig)`` tuple, or ``None`` if no eligible task was found.
        """
