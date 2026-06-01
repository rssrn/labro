"""Agent registry — maps CLI id → Agent instance.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

from labro.agents.base import Agent
from labro.agents.claude_code import ClaudeCodeAgent
from labro.agents.codex import CodexAgent

_REGISTRY: dict[str, Agent] = {
    ClaudeCodeAgent.id: ClaudeCodeAgent(),
    CodexAgent.id: CodexAgent(),
}


def get_agent(agent_id: str) -> Agent:
    """Return the Agent for *agent_id*, raising ValueError if unknown."""
    if agent_id not in _REGISTRY:
        valid = ", ".join(f"'{k}'" for k in sorted(_REGISTRY))
        raise ValueError(f"Unknown agent {agent_id!r}. Valid agents: {valid}")
    return _REGISTRY[agent_id]


def all_agents() -> list[Agent]:
    """Return all registered Agent instances."""
    return list(_REGISTRY.values())
