"""labro.toml loader: tomllib parse + Pydantic validation + env-var presence checks.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from labro.config.schema import GhLabelSource, GrafanaAlertsSource, LabroConfig, parse_slug


class ConfigError(Exception):
    """Raised for any hard configuration or environment error."""


def referenced_agents(config: LabroConfig) -> set[str]:
    """Return the set of agent CLI ids referenced by any model slug in the config."""
    slugs: list[str] = [config.defaults.model]

    for rule in config.shared_rules.values():
        if rule.model is not None:
            slugs.append(rule.model)

    for project in config.projects:
        if project.model is not None:
            slugs.append(project.model)
        for source in project.task_sources:
            if source.model is not None:
                slugs.append(source.model)
            if isinstance(source, GhLabelSource):
                for lr in source.label_rules:
                    if lr.model is not None:
                        slugs.append(lr.model)
                for ar in source.actor_rules:
                    if ar.model is not None:
                        slugs.append(ar.model)

    return {parse_slug(s).agent for s in slugs}


def required_env_vars(config: LabroConfig) -> list[str]:
    """Return env var names that must each be present (excluding agent auth).

    Rules (from ARCHITECTURE §8):
    - GH_TOKEN: required unless GitHub App auth is configured.
    - GITHUB_APP_PRIVATE_KEY: required when GitHub App auth is configured (replaces GH_TOKEN).
    - Agent auth: checked separately by load_config via the agent registry.
    - GRAFANA_TOKEN: required if any project has a grafana-alerts source.
    - SLACK_WEBHOOK_URL: required if digest is enabled.
    """
    required: list[str] = []

    if config.github_app_id is not None:
        # GitHub App auth: private key supplied via env var; no GH_TOKEN needed.
        required.append("GITHUB_APP_PRIVATE_KEY")
    else:
        required.append("GH_TOKEN")

    if config.digest.enabled:
        required.append("SLACK_WEBHOOK_URL")

    has_grafana = any(
        isinstance(source, GrafanaAlertsSource)
        for project in config.projects
        for source in project.task_sources
    )
    if has_grafana:
        required.append("GRAFANA_TOKEN")

    return required


def load_config(path: Path) -> LabroConfig:
    """Parse and validate labro.toml at *path*.

    Raises:
        ConfigError: on TOML syntax error, Pydantic validation failure,
            missing env var, missing agent auth, or unknown agent id.
    """
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ConfigError(f"Cannot read config file {path}: {exc}") from exc

    try:
        data = tomllib.loads(raw.decode())
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"TOML parse error in {path}: {exc}") from exc

    try:
        config = LabroConfig.model_validate(data)
    except Exception as exc:
        raise ConfigError(f"Config validation error: {exc}") from exc

    missing = [var for var in required_env_vars(config) if not os.environ.get(var)]
    if missing:
        raise ConfigError(f"Missing required environment variable(s): {', '.join(missing)}")

    # Per-agent auth check (fast env/file check, not full HTTP validation)
    from labro.agents.registry import get_agent

    for agent_id in sorted(referenced_agents(config)):
        try:
            agent = get_agent(agent_id)
        except ValueError as exc:
            raise ConfigError(str(exc)) from exc
        if not agent.has_auth():
            auth_vars = ", ".join(agent.auth_env_vars)
            raise ConfigError(
                f"Missing auth for agent '{agent_id}': set {auth_vars}"
                + (" or provide ~/.codex/auth.json" if agent_id == "codex" else "")
            )

    return config
