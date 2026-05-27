"""Labro command-line interface.

Entry point: ``labro`` (configured in ``pyproject.toml`` as
``[project.scripts] labro = "labro.cli:main"``).

Supported commands:
  labro run <project> [--dry-run]

Dry-run path (ARCHITECTURE runtime view line 344):
  load config → resolve project → run picker + prompt_builder
  → print resolved task, agent config, full prompt → exit

Live path (M2+):
  load config → resolve project → check LABRO_DISABLED → acquire lock
  → budget check → pick task → prepare repo → build prompt
  → invoke agent → write run record → release lock

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

import labro.logger as logger_mod
import labro.store as store_mod
from labro.agents.claude_code import ClaudeCodeAgent
from labro.config.loader import ConfigError, load_config
from labro.config.schema import LabroConfig, ProjectConfig
from labro.picker import pick
from labro.prompt_builder import build_prompt
from labro.repo import prepare_repo
from labro.runner import RunnerOutputError, RunnerTimeoutError

_log = logging.getLogger(__name__)


def _default_config_path() -> Path:
    """Resolve the config path from ``LABRO_CONFIG`` env var or fall back to ``./labro.toml``.

    Precedence (highest first):
      1. ``--config`` CLI flag (handled by argparse; overrides this default)
      2. ``LABRO_CONFIG`` environment variable
      3. ``./labro.toml`` in the current working directory
    """
    env = os.environ.get("LABRO_CONFIG")
    return Path(env) if env else Path("labro.toml")


def _default_db_path() -> Path:
    """Resolve the SQLite DB path from ``LABRO_DB_PATH`` env var or ``/data/labro.db``."""
    env = os.environ.get("LABRO_DB_PATH")
    return Path(env) if env else Path("/data/labro.db")


def _default_repos_dir() -> Path:
    """Resolve the repos mount dir from ``LABRO_REPOS_DIR`` env var or default to ``/repos``."""
    env = os.environ.get("LABRO_REPOS_DIR")
    return Path(env) if env else Path("/repos")


def _find_project(config: LabroConfig, name: str) -> ProjectConfig | None:
    """Return the first project whose name matches *name*, or ``None``."""
    for project in config.projects:
        if project.name == name:
            return project
    return None


def _now_utc() -> str:
    """Return the current UTC time as an ISO 8601 string (e.g. ``2024-01-15T10:00:00Z``)."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Dry-run path ───────────────────────────────────────────────────────────────


def _cmd_run_dryrun(config_path: Path, project_name: str) -> int:
    """Dry-run: resolve task + agent config + prompt and print without side effects."""
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


# ── Live run path ──────────────────────────────────────────────────────────────


def _cmd_run_live(
    config_path: Path,
    project_name: str,
    db_path: Path,
    repos_dir: Path,
) -> int:
    """Live run: full M2 run loop — lock → budget → pick → agent → log."""
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

    # LABRO_DISABLED check — before lock acquisition; no SQLite record written
    disabled_flag = db_path.parent / "LABRO_DISABLED"
    if disabled_flag.exists():
        print("skipped: harness disabled (LABRO_DISABLED flag present)")
        return 0

    # Open database
    conn = store_mod.open_db(db_path)
    lock_timeout_s = (
        project.timeout_s if project.timeout_s is not None else config.defaults.timeout_s
    )

    # Acquire run lock
    if not store_mod.acquire_lock(conn, project_name, lock_timeout_s):
        print(f"skipped: run in progress for project {project_name!r}")
        conn.close()
        return 0

    run_id = str(uuid.uuid4())
    started_at = _now_utc()

    try:
        # ── Budget check ───────────────────────────────────────────────────────
        if project.daily_budget_usd is not None and project.daily_budget_usd > 0:
            spend = store_mod.get_daily_spend(conn, project_name)
            if spend >= project.daily_budget_usd:
                ended_at = _now_utc()
                reason = (
                    f"skipped: daily budget exceeded"
                    f" (${spend:.2f} of ${project.daily_budget_usd:.2f} used)"
                )
                logger_mod.write_run(
                    conn,
                    run_id=run_id,
                    project=project_name,
                    task=None,
                    agent_cfg=None,
                    agent_result=None,
                    outcome="skipped",
                    failure_reason=reason,
                    started_at=started_at,
                    ended_at=ended_at,
                )
                print(reason)
                return 0

        # ── Pick task ──────────────────────────────────────────────────────────
        task, agent_cfg = pick(project, config)
        if task is None or agent_cfg is None:
            ended_at = _now_utc()
            logger_mod.write_run(
                conn,
                run_id=run_id,
                project=project_name,
                task=None,
                agent_cfg=None,
                agent_result=None,
                outcome="skipped",
                failure_reason="skipped: no task found",
                started_at=started_at,
                ended_at=ended_at,
            )
            print(f"skipped: no eligible task found for project {project_name!r}")
            return 0

        # ── Prepare repo ───────────────────────────────────────────────────────
        repo_path = prepare_repo(task.repo, repos_dir)
        _log.info("repo ready at %s", repo_path)
        # Set agent working directory to the cloned repo (ARCHITECTURE line 630).
        agent_cfg.cwd = repo_path

        # ── Build prompt ───────────────────────────────────────────────────────
        prompt = build_prompt(task=task, project_context=project.context)

        # ── Invoke agent ───────────────────────────────────────────────────────
        from labro.models import AgentResult

        agent_result: AgentResult | None = None
        outcome = "failure"
        failure_reason: str | None = None

        try:
            agent_result = ClaudeCodeAgent().invoke(prompt, agent_cfg)
            # "partial" counts as failure in the runs table (ARCHITECTURE line 263)
            outcome = "failure" if agent_result.outcome in ("failure", "partial") else "success"
            failure_reason = agent_result.failure_reason
        except RunnerTimeoutError:
            failure_reason = "timeout"
        except RunnerOutputError as exc:
            failure_reason = str(exc)

        # ── Write run record ───────────────────────────────────────────────────
        ended_at = _now_utc()
        logger_mod.write_run(
            conn,
            run_id=run_id,
            project=project_name,
            task=task,
            agent_cfg=agent_cfg,
            agent_result=agent_result,
            outcome=outcome,
            failure_reason=failure_reason,
            started_at=started_at,
            ended_at=ended_at,
        )

        print(f"run complete: outcome={outcome!r} run_id={run_id}")
        return 0 if outcome == "success" else 1

    finally:
        store_mod.release_lock(conn, project_name)
        conn.close()


# ── CLI dispatch ───────────────────────────────────────────────────────────────


def _cmd_run(args: argparse.Namespace) -> int:
    """Handle ``labro run <project> [--dry-run]``."""
    config_path: Path = args.config
    project_name: str = args.project
    dry_run: bool = args.dry_run

    if dry_run:
        return _cmd_run_dryrun(config_path, project_name)

    db_path: Path = args.db_path
    repos_dir: Path = args.repos_dir
    return _cmd_run_live(config_path, project_name, db_path, repos_dir)


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
        help="Run Labro for a project",
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
    run_parser.add_argument(
        "--db-path",
        type=Path,
        default=_default_db_path(),
        metavar="PATH",
        help=(
            "Path to the SQLite database"
            " (default: $LABRO_DB_PATH if set, otherwise /data/labro.db)"
        ),
    )
    run_parser.add_argument(
        "--repos-dir",
        type=Path,
        default=_default_repos_dir(),
        metavar="DIR",
        help=(
            "Directory for cloned repositories"
            " (default: $LABRO_REPOS_DIR if set, otherwise /repos)"
        ),
    )
    run_parser.set_defaults(func=_cmd_run)

    return parser


def main() -> None:
    """Entry point for the ``labro`` CLI."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = _build_parser()
    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
