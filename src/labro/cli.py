"""Labro command-line interface.

Entry point: ``labro`` (configured in ``pyproject.toml`` as
``[project.scripts] labro = "labro.cli:main"``).

M1 supports only:
  labro run <project> --dry-run

The dry-run path (ARCHITECTURE runtime view line 344):
  load config → resolve project → run picker + prompt_builder
  → print resolved task, agent config, full prompt → exit

No lock, repo prep, agent invocation, SQLite writes, or label transitions.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from labro.config.loader import ConfigError, load_config
from labro.config.schema import LabroConfig, ProjectConfig
from labro.picker import pick
from labro.prompt_builder import build_prompt


def _default_config_path() -> Path:
    """Resolve the config path from ``LABRO_CONFIG`` env var or fall back to ``./labro.toml``.

    Precedence (highest first):
      1. ``--config`` CLI flag (handled by argparse; overrides this default)
      2. ``LABRO_CONFIG`` environment variable
      3. ``./labro.toml`` in the current working directory
    """
    env = os.environ.get("LABRO_CONFIG")
    return Path(env) if env else Path("labro.toml")


def _find_project(config: LabroConfig, name: str) -> ProjectConfig | None:
    """Return the first project whose name matches *name*, or ``None``."""
    for project in config.projects:
        if project.name == name:
            return project
    return None


def _cmd_run(args: argparse.Namespace) -> int:
    """Handle ``labro run <project> [--dry-run]``."""
    config_path: Path = args.config
    project_name: str = args.project
    dry_run: bool = args.dry_run

    if not dry_run:
        print(
            "error: only --dry-run is supported in M1." " Omit --dry-run for a live run (M2+).",
            file=sys.stderr,
        )
        return 2

    # Load and validate config
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    # Resolve project
    project = _find_project(config, project_name)
    if project is None:
        names = ", ".join(p.name for p in config.projects) or "(none)"
        print(
            f"error: no project named {project_name!r} in {config_path}." f" Available: {names}",
            file=sys.stderr,
        )
        return 1

    if not project.enabled:
        print(f"warning: project {project_name!r} is disabled (enabled = false).")

    # Pick task
    task, agent_cfg = pick(project, config)

    if task is None or agent_cfg is None:
        print(
            f"[dry-run] No eligible task found for project {project_name!r}."
            " All sources returned nothing."
        )
        return 0

    # Build prompt
    prompt = build_prompt(
        task=task,
        project_context=project.context,
    )

    # ── Dry-run output ─────────────────────────────────────────────────────────
    print("=" * 72)
    print("SELECTED TASK")
    print("=" * 72)
    print(f"  task_id          : {task.task_id}")
    print(f"  source           : {task.source}")
    print(f"  repo             : {task.repo}")
    print(f"  item_type        : {task.item_type}")
    print(f"  item_number      : {task.item_number}")
    print(f"  item_url         : {task.item_url}")
    print(f"  source_label     : {task.source_label}")
    print(f"  done_label       : {task.done_label}")
    if task.grafana_rule_uid is not None:
        print(f"  grafana_rule_uid : {task.grafana_rule_uid}")
    actions_str = ", ".join(a.value for a in task.permitted_actions) or "(none)"
    print(f"  permitted_actions: {actions_str}")
    print()
    print("  description:")
    for line in task.description.splitlines():
        print(f"    {line}")

    print()
    print("=" * 72)
    print("AGENT CONFIG")
    print("=" * 72)
    print(f"  agent     : {agent_cfg.agent}")
    print(f"  model     : {agent_cfg.model}")
    print(f"  max_turns : {agent_cfg.max_turns}")
    print(f"  timeout_s : {agent_cfg.timeout_s}")

    print()
    print("=" * 72)
    print("FULL PROMPT")
    print("=" * 72)
    print(prompt)

    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="labro",
        description="Labro — AI coding agent harness",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=_default_config_path(),
        metavar="PATH",
        help=("Path to labro.toml" " (default: $LABRO_CONFIG if set, otherwise ./labro.toml)"),
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser(
        "run",
        help="Run Labro for a project (M1: --dry-run only)",
    )
    run_parser.add_argument(
        "project",
        help="Name of the project to run (matches labro.toml [[projects]] name)",
    )
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help=(
            "Resolve and print task + agent config + prompt without invoking the"
            " agent, acquiring a lock, or writing any state"
        ),
    )
    run_parser.set_defaults(func=_cmd_run)

    return parser


def main() -> None:
    """Entry point for the ``labro`` CLI."""
    parser = _build_parser()
    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
