"""labro.toml loader: tomllib parse + Pydantic validation + env-var presence checks.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

from labro.config.schema import GrafanaAlertsSource, LabroConfig


class ConfigError(Exception):
    """Raised for any hard configuration or environment error."""


def _required_env_vars(config: LabroConfig) -> list[str]:
    """Return the list of env var names that must be present for this config.

    Rules (from ARCHITECTURE §8):
    - GH_TOKEN: always required.
    - ANTHROPIC_API_KEY: always required.
    - GRAFANA_TOKEN: required if any project has a grafana-alerts source.
    - SLACK_WEBHOOK_URL: required if digest is enabled.
    """
    required: list[str] = ["GH_TOKEN", "ANTHROPIC_API_KEY"]

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
        ConfigError: TOML syntax error, Pydantic validation failure, or missing
            required environment variable.
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

    missing = [var for var in _required_env_vars(config) if not os.environ.get(var)]
    if missing:
        raise ConfigError(f"Missing required environment variable(s): {', '.join(missing)}")

    return config
