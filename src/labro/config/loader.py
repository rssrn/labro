"""labro.toml loader: tomllib parse + Pydantic validation + env-var presence checks.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import logging
import os
import tomllib
from pathlib import Path

from labro.config.schema import (
    GhAuthorSource,
    GhLabelSource,
    GrafanaAlertsSource,
    LabroConfig,
    parse_slug,
)

logger = logging.getLogger(__name__)


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
            elif isinstance(source, GhAuthorSource):
                for ar in source.author_rules:
                    if ar.model is not None:
                        slugs.append(ar.model)

    return {parse_slug(s).agent for s in slugs}


def required_env_vars(config: LabroConfig) -> list[str]:
    """Return env var names that must each be present (excluding agent auth).

    Rules (from ARCHITECTURE §8):
    - GH_TOKEN: required unless GitHub App auth is configured.
    - GH_APP_PRIVATE_KEY: required when GitHub App auth is configured (replaces GH_TOKEN).
    - Agent auth: checked separately by load_config via the agent registry.
    - GRAFANA_TOKEN: required if any project has a grafana-alerts source.
    - SLACK_WEBHOOK_URL: required if digest is enabled.
    """
    required: list[str] = []

    if config.github_app_id is not None:
        # GitHub App auth: private key via env var (base64 or plain); no GH_TOKEN needed.
        # Accept either form; resolve_private_key_pem() picks the right one at runtime.
        if not os.environ.get("GH_APP_PRIVATE_KEY_BASE64") and not os.environ.get(
            "GH_APP_PRIVATE_KEY"
        ):
            required.append("GH_APP_PRIVATE_KEY or GH_APP_PRIVATE_KEY_BASE64")
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

    if config.dashboard.enabled:
        for r2_var in ("R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_ACCOUNT_ID", "R2_BUCKET"):
            required.append(r2_var)

    return required


def load_config(path: Path, perspectives_path: Path | None = None) -> LabroConfig:
    """Parse and validate labro.toml at *path*.

    If *perspectives_path* is None, ``perspectives.toml`` is auto-discovered
    in the same directory as *path*.  If absent, perspective injection is
    disabled and a warning is logged.

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

    # Merge perspectives.toml if present.
    # Resolution order: explicit arg → LABRO_PERSPECTIVES env var → sibling of config → absent.
    if perspectives_path is None:
        env_persp = os.environ.get("LABRO_PERSPECTIVES")
        persp_path = Path(env_persp) if env_persp else path.parent / "perspectives.toml"
    else:
        persp_path = perspectives_path
    if persp_path.exists():
        try:
            persp_data = tomllib.loads(persp_path.read_bytes().decode())
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"TOML parse error in {persp_path}: {exc}") from exc
        data.setdefault("perspectives", {}).update(persp_data.get("perspectives", {}))
    else:
        logger.info(
            "perspectives.toml not found at %s — perspective injection disabled", persp_path
        )

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
