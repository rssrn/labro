"""Priority-stack task picker.

Iterates the configured task sources top-to-bottom; the first non-None result
wins.  A source that raises is treated as ``skipped: source error — <name>``
and the picker moves to the next source (ARCHITECTURE line 731).

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import logging

from labro.config.schema import (
    GhDelegatedSource as GhDelegatedSourceConfig,
)
from labro.config.schema import (
    LabroConfig,
    ProjectConfig,
)
from labro.models import AgentConfig, Task
from labro.task_sources.base import TaskSource
from labro.task_sources.gh_delegated import GhDelegatedTaskSource

logger = logging.getLogger(__name__)


def _build_source(source_config: object) -> TaskSource | None:
    """Instantiate a TaskSource from a config object.

    Returns ``None`` for source types that are not yet implemented (M2+).
    """
    if isinstance(source_config, GhDelegatedSourceConfig):
        return GhDelegatedTaskSource(source_config)
    # GrafanaAlertsSource and ProactiveImprovementSource are M2+ — skip gracefully.
    return None


def pick(
    project: ProjectConfig,
    config: LabroConfig,
) -> tuple[Task, AgentConfig] | tuple[None, None]:
    """Iterate the project's task sources and return the first available task.

    Args:
        project: The project whose sources should be evaluated.
        config: The full parsed config (provides ``[defaults]``).

    Returns:
        ``(Task, AgentConfig)`` if a source yields a task, otherwise ``(None, None)``.
    """
    defaults = config.defaults

    for source_cfg in project.task_sources:
        source = _build_source(source_cfg)
        if source is None:
            # Source type not implemented yet — skip silently.
            continue

        source_name = getattr(source_cfg, "type", repr(source_cfg))
        try:
            result = source.fetch_task(
                project=project,
                defaults_model=defaults.model,
                defaults_max_turns=defaults.max_turns,
                defaults_timeout_s=defaults.timeout_s,
                defaults_max_comments=defaults.max_comments,
            )
        except Exception:
            logger.warning("skipped: source error — %s", source_name, exc_info=True)
            continue

        if result is not None:
            return result

    return None, None
