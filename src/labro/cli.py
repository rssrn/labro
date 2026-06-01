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
import json
import logging
import logging.handlers
import os
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path

import labro.assignee as assignee_mod
import labro.logger as logger_mod
import labro.post_run as post_run_mod
import labro.store as store_mod
from labro.agents.claude_code import ClaudeCodeAgent
from labro.config.loader import ConfigError, load_config, required_env_vars
from labro.config.schema import GhLabelSource, LabroConfig, PermittedAction, ProjectConfig
from labro.models import AgentResult, Task
from labro.picker import pick
from labro.prompt_builder import build_prompt
from labro.repo import prepare_repo, preserve_wip
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


def _default_log_path() -> Path:
    """Resolve the log file path from ``LABRO_LOG_PATH`` env var or ``/data/labro.log``."""
    env = os.environ.get("LABRO_LOG_PATH")
    return Path(env) if env else Path("/data/labro.log")


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
            f"error: no project named {project_name!r} in {config_path}. Available: {names}",
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
    if task.assignees:
        print(f"  assignees        : {', '.join(task.assignees)}")
    if config.claude_assignee and task.item_number is not None:
        print(f"  [dry-run] would assign {config.claude_assignee!r} during run")
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
            f"error: no project named {project_name!r} in {config_path}. Available: {names}",
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
    # Set to the task after assign_claude so the finally block knows to restore.
    _assigned_task: Task | None = None

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

        # Write items_touched row before agent runs (item already known for gh-label)
        if task.item_number is not None:
            store_mod.insert_items_touched(
                conn,
                run_id=run_id,
                repo=task.repo,
                item_type=task.item_type or "issue",
                item_number=task.item_number,
            )

        # ── Detect prior WIP branch for resume ─────────────────────────────────
        prior_wip_branch: str | None = None
        prior_summary: str | None = None
        if task.item_url:
            prior = store_mod.get_prior_wip_run(conn, task.item_url)
            if prior is not None:
                prior_wip_url, prior_summary = prior
                # Extract branch name from URL: …/tree/<branch>
                prior_wip_branch = (
                    prior_wip_url.split("/tree/", 1)[1] if "/tree/" in prior_wip_url else None
                )
                _log.info(
                    "prior WIP branch found; will attempt to resume %s",
                    prior_wip_branch,
                )

        # ── Prepare repo ───────────────────────────────────────────────────────
        repo_path, checked_out_wip = prepare_repo(
            task.repo, repos_dir, wip_branch=prior_wip_branch
        )
        if prior_wip_branch is not None and checked_out_wip is None:
            _log.warning(
                "WIP branch %s not found on remote; agent will start from scratch",
                prior_wip_branch,
            )
            prior_wip_branch = None
            prior_summary = None
        _log.info("repo ready at %s", repo_path)
        # Set agent working directory to the cloned repo (ARCHITECTURE line 630).
        agent_cfg.cwd = repo_path

        # ── Build prompt ───────────────────────────────────────────────────────
        prompt = build_prompt(
            task=task,
            project_context=project.context,
            wip_branch=prior_wip_branch,
            prior_summary=prior_summary,
        )

        # ── Assign Claude user (optional) ──────────────────────────────────────
        if config.claude_assignee and task.item_number is not None:
            assignee_mod.comment_assignment(task, config.claude_assignee)
            assignee_mod.assign_claude(task, config.claude_assignee)
            _assigned_task = task

        # ── Invoke agent ───────────────────────────────────────────────────────
        agent_result: AgentResult | None = None
        outcome = "failure"
        failure_reason: str | None = None

        item_ref = (
            f"{task.item_type} #{task.item_number}"
            if task.item_number is not None
            else "(no item)"
        )
        _log.info(
            "invoking agent %s (model=%s) on %s %s",
            agent_cfg.agent,
            agent_cfg.model,
            task.repo,
            item_ref,
        )
        try:
            agent_result = ClaudeCodeAgent().invoke(prompt, agent_cfg)
            outcome = agent_result.outcome
            failure_reason = agent_result.failure_reason
        except RunnerTimeoutError:
            failure_reason = "timeout"
        except RunnerOutputError as exc:
            failure_reason = str(exc)

        # ── WIP preservation (non-success outcomes) ────────────────────────────
        wip_branch_url: str | None = None
        if outcome != "success":
            # For session_limit_hit: only attempt WIP preservation if the agent
            # produced output (it ran at least some turns) AND the task config
            # permits pushing (so the harness has write access to the repo).
            if failure_reason == "session_limit_hit" and (
                agent_result is None
                or agent_result.output_tokens == 0
                or PermittedAction.PUSH_DEFAULT not in task.permitted_actions
            ):
                pass  # skip WIP preservation — issue will be re-queued as-is
            else:
                wip_branch_url = preserve_wip(repo_path, task.repo, run_id)

        # ── Post-run label transitions ─────────────────────────────────────────
        post_run_mod.post_run(
            run_id,
            task,
            agent_result,
            outcome=outcome,
            agent_name=agent_cfg.agent,
            wip_branch_url=wip_branch_url,
            resuming_wip=prior_wip_branch is not None,
        )

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
            wip_branch_url=wip_branch_url,
        )

        if outcome == "success":
            _log.info("run complete: outcome=%r run_id=%s", outcome, run_id)
        else:
            _log.warning(
                "run complete: outcome=%r run_id=%s failure_reason=%s",
                outcome,
                run_id,
                failure_reason,
            )
        print(f"run complete: outcome={outcome!r} run_id={run_id}")
        return 0 if outcome == "success" else 1

    finally:
        if _assigned_task is not None and config.claude_assignee:
            assignee_mod.restore_assignees(_assigned_task, config.claude_assignee)
        store_mod.release_lock(conn, project_name)
        conn.close()


# ── Operator helpers ───────────────────────────────────────────────────────────

_CLAUDE_AUTH_VARS = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")


def _run_gh(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a gh CLI command (list-form, shell=False) and return the result.

    @author Claude Sonnet 4.6 Anthropic
    """
    return subprocess.run(cmd, capture_output=True, text=True, shell=False)


def _collect_labels_for_project(project: ProjectConfig, _config: LabroConfig) -> list[str]:
    """Return the deduplicated list of GitHub labels that must exist for *project*.

    Always includes ai-failed and ai-contributed; also collects label/done_label
    from each gh-label source's rules. shared_rules are already expanded by the
    Pydantic validator, so rule.label / rule.done_label are always populated.

    @author Claude Sonnet 4.6 Anthropic
    """
    seen: set[str] = set()
    labels: list[str] = []

    def _add(label: str | None) -> None:
        if label and label not in seen:
            seen.add(label)
            labels.append(label)

    _add("ai-failed")
    _add("ai-contributed")

    for source in project.task_sources:
        if isinstance(source, GhLabelSource):
            for lr in source.label_rules:
                _add(lr.label)
                _add(lr.done_label)
            for ar in source.actor_rules:
                _add(ar.done_label)

    return labels


def _trunc(s: str | None, n: int) -> str:
    """Truncate *s* to *n* characters, appending … if needed."""
    if not s:
        return ""
    return s if len(s) <= n else s[: n - 1] + "…"


# ── labro init ─────────────────────────────────────────────────────────────────


def _cmd_init(args: argparse.Namespace) -> int:
    """Create (or update) GitHub labels for all configured projects.

    @author Claude Sonnet 4.6 Anthropic
    """
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    projects = [p for p in config.projects if p.enabled]
    if args.project:
        projects = [p for p in projects if p.name == args.project]
        if not projects:
            names = ", ".join(p.name for p in config.projects) or "(none)"
            print(
                f"error: no project named {args.project!r}. Available: {names}",
                file=sys.stderr,
            )
            return 1

    had_error = False
    total_labels = 0
    for project in projects:
        for label in _collect_labels_for_project(project, config):
            result = _run_gh(["gh", "label", "create", label, "--repo", project.repo, "--force"])
            if result.returncode != 0:
                print(f"WARN  [{project.name}] {label}: {result.stderr.strip()}")
                had_error = True
            else:
                print(f"OK    [{project.name}] {label}")
            total_labels += 1

    print(f"\nCreated/verified {total_labels} label(s) across {len(projects)} project(s).")
    return 1 if had_error else 0


# ── labro check ────────────────────────────────────────────────────────────────


def _check_anthropic_api_key(api_key: str) -> tuple[str, str]:
    """Validate ANTHROPIC_API_KEY by calling GET /v1/models (no tokens spent).

    @author Claude Sonnet 4.6 Anthropic
    """
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/models",
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10):  # noqa: S310
            return ("OK  ", "ANTHROPIC_API_KEY: valid (GET /v1/models succeeded)")
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            return ("FAIL", "ANTHROPIC_API_KEY: invalid or expired (401 Unauthorized)")
        return ("WARN", f"ANTHROPIC_API_KEY: unexpected HTTP {exc.code} from /v1/models")
    except Exception as exc:
        return ("WARN", f"ANTHROPIC_API_KEY: could not reach api.anthropic.com: {exc}")


def _cmd_check(args: argparse.Namespace) -> int:
    """Pre-flight health check: config, env vars, labels, collaborator.

    @author Claude Sonnet 4.6 Anthropic
    """
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"FAIL config: {exc}")
        return 1

    results: list[tuple[str, str]] = []

    # Env vars (excluding Claude auth — checked separately below)
    for var in required_env_vars(config):
        if not os.environ.get(var):
            results.append(("FAIL", f"env var {var} not set"))
        else:
            results.append(("OK  ", f"env var {var}"))

    # Claude auth
    if not any(os.environ.get(v) for v in _CLAUDE_AUTH_VARS):
        results.append(
            (
                "FAIL",
                f"no Claude auth — set {_CLAUDE_AUTH_VARS[0]} or {_CLAUDE_AUTH_VARS[1]}",
            )
        )
    elif os.environ.get("ANTHROPIC_API_KEY"):
        results.append(_check_anthropic_api_key(os.environ["ANTHROPIC_API_KEY"]))
    else:
        # No zero-cost validation path exists for OAuth tokens: `claude auth status`
        # reports the auth method but does not verify the token value against the API.
        results.append(
            ("WARN", "Claude auth (CLAUDE_CODE_OAUTH_TOKEN) — env var present but not validated")
        )

    # GitHub token connectivity
    gh_auth = _run_gh(["gh", "auth", "status"])
    if gh_auth.returncode == 0:
        results.append(("OK  ", "gh auth status: authenticated"))
    else:
        msg = gh_auth.stderr.strip() or "not authenticated"
        results.append(("FAIL", f"gh auth status: {msg}"))

    # Per-project checks
    projects = [p for p in config.projects if p.enabled]
    if args.project:
        projects = [p for p in projects if p.name == args.project]

    for project in projects:
        expected = set(_collect_labels_for_project(project, config))

        gh_result = _run_gh(
            ["gh", "label", "list", "--repo", project.repo, "--json", "name", "--limit", "200"]
        )
        if gh_result.returncode != 0:
            results.append(
                ("FAIL", f"[{project.name}] gh label list failed: {gh_result.stderr.strip()}")
            )
        else:
            existing = {obj["name"] for obj in json.loads(gh_result.stdout)}
            for label in sorted(expected - existing):
                results.append(("FAIL", f"[{project.name}] label missing: {label!r}"))
            if not (expected - existing):
                results.append(("OK  ", f"[{project.name}] all {len(expected)} labels present"))

        if config.claude_assignee:
            collab_result = _run_gh(
                [
                    "gh",
                    "api",
                    f"repos/{project.repo}/collaborators/{config.claude_assignee}",
                ]
            )
            if collab_result.returncode == 0:
                results.append(
                    (
                        "OK  ",
                        f"[{project.name}] claude_assignee {config.claude_assignee!r}"
                        " is a collaborator",
                    )
                )
            else:
                results.append(
                    (
                        "FAIL",
                        f"[{project.name}] claude_assignee {config.claude_assignee!r}"
                        " not a collaborator (or gh api failed)",
                    )
                )

    for status, message in results:
        print(f"{status} {message}")

    return 1 if any(s.strip() == "FAIL" for s, _ in results) else 0


# ── labro review ───────────────────────────────────────────────────────────────


def _cmd_review(args: argparse.Namespace) -> int:
    """Print tabular run history from SQLite.

    @author Claude Sonnet 4.6 Anthropic
    """
    db_path: Path = args.db_path
    if not db_path.exists():
        print(f"No database at {db_path}. Run 'labro run' to create it.")
        return 0

    conn = store_mod.open_db(db_path)
    rows = store_mod.query_runs(
        conn,
        project=args.project,
        outcome=args.outcome,
        limit=args.limit,
    )
    conn.close()

    if not rows:
        print("No runs found.")
        return 0

    # Column widths
    W = (16, 18, 9, 14, 40, 8, 9, 6, 55)
    headers = (
        "started_at",
        "project",
        "outcome",
        "source",
        "item_url",
        "dur_s",
        "cost_usd",
        "turns",
        "summary",
    )

    def _row_line(vals: tuple[str, ...]) -> str:
        parts = []
        for i, v in enumerate(vals):
            parts.append(v.ljust(W[i]) if i < len(W) - 1 else v)
        return "  ".join(parts)

    sep = "  ".join("-" * w for w in W)
    print(_row_line(headers))
    print(sep)

    total_cost = 0.0
    total_tokens = 0
    for row in rows:
        started = (row["started_at"] or "")[:16]
        cost = row["total_cost_usd"] or 0.0
        tokens = (
            (row["input_tokens"] or 0)
            + (row["output_tokens"] or 0)
            + (row["cache_read_tokens"] or 0)
            + (row["cache_write_tokens"] or 0)
        )
        total_cost += cost
        total_tokens += tokens

        dur = f"{row['duration_s']:.1f}" if row["duration_s"] is not None else "-"
        cost_str = f"${cost:.4f}"
        turns = str(row["turns_used"] or "-")

        vals = (
            started,
            _trunc(row["project"], W[1]),
            _trunc(row["outcome"], W[2]),
            _trunc(row["task_source"], W[3]),
            _trunc(row["item_url"], W[4]),
            dur.rjust(W[5]),
            cost_str.rjust(W[6]),
            turns.rjust(W[7]),
            _trunc(row["summary"], W[8]),
        )
        print(_row_line(vals))

    print(
        f"\n{len(rows)} run(s) shown  |  total cost: ${total_cost:.4f}"
        f"  |  total tokens: {total_tokens:,}"
    )
    return 0


# ── labro list-locks ───────────────────────────────────────────────────────────


def _cmd_list_locks(args: argparse.Namespace) -> int:
    """Show currently held project locks with age.

    @author Claude Sonnet 4.6 Anthropic
    """
    db_path: Path = args.db_path
    if not db_path.exists():
        print(f"No database at {db_path}.")
        return 0

    config: LabroConfig | None = None
    try:
        config = load_config(args.config)
    except ConfigError:
        pass  # best-effort; stale detection falls back to defaults

    default_timeout_s = config.defaults.timeout_s if config else 600

    conn = store_mod.open_db(db_path)
    rows = store_mod.list_locks(conn)
    conn.close()

    if not rows:
        print("No locks held.")
        return 0

    now = datetime.now(UTC)
    for row in rows:
        locked_at_str: str = row["locked_at"]
        locked_at = datetime.fromisoformat(locked_at_str.replace("Z", "+00:00"))
        if locked_at.tzinfo is None:
            locked_at = locked_at.replace(tzinfo=UTC)
        age_s = (now - locked_at).total_seconds()

        timeout_s = default_timeout_s
        if config:
            proj = _find_project(config, row["project"])
            if proj and proj.timeout_s is not None:
                timeout_s = proj.timeout_s

        stale = age_s > timeout_s + 60
        stale_marker = "  [STALE]" if stale else ""
        print(f"  {row['project']:<24} locked_at={locked_at_str}  age={age_s:.0f}s{stale_marker}")

    return 0


# ── labro unlock ───────────────────────────────────────────────────────────────


def _cmd_unlock(args: argparse.Namespace) -> int:
    """Manually release a stale project lock.

    @author Claude Sonnet 4.6 Anthropic
    """
    db_path: Path = args.db_path
    if not db_path.exists():
        print(f"No database at {db_path}.")
        return 0

    conn = store_mod.open_db(db_path)

    row = conn.execute(
        "SELECT locked_at FROM project_locks WHERE project = ?", (args.project,)
    ).fetchone()

    store_mod.release_lock(conn, args.project)
    conn.close()

    if row is not None:
        print(f"Released lock for {args.project!r} (held since {row['locked_at']}).")
    else:
        print(f"No lock held for {args.project!r}.")

    return 0


# ── gen-crontab ────────────────────────────────────────────────────────────────

_CRONTAB_HEADER = """\
# /etc/cron.d/labro — generated by entrypoint.sh at container start. Do not edit.
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin:/usr/local/bin
"""


def _cmd_gen_crontab(args: argparse.Namespace) -> int:
    """Output a /etc/cron.d/labro file derived from labro.toml to stdout."""
    config_path: Path = args.config
    try:
        config = load_config(config_path)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    log_path = os.environ.get("LABRO_LOG_PATH", "/data/labro.log")
    lines = [_CRONTAB_HEADER, "# Projects"]
    for project in config.projects:
        if not project.enabled:
            continue
        lines.append(
            f"{project.cron}   root  . /etc/labro-env;"
            f" labro run {project.name}  >> {log_path}  2>&1"
        )

    if config.digest.enabled:
        lines.append("")
        lines.append("# Digest (covers all projects)")
        lines.append(
            f"{config.digest.cron}   root  . /etc/labro-env; labro digest  >> {log_path}  2>&1"
        )

    print("\n".join(lines))
    return 0


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
        help=("Path to labro.toml (default: $LABRO_CONFIG if set, otherwise ./labro.toml)"),
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

    gen_crontab_parser = subparsers.add_parser(
        "gen-crontab",
        help="Print a /etc/cron.d/labro crontab to stdout (used by entrypoint.sh)",
    )
    gen_crontab_parser.set_defaults(func=_cmd_gen_crontab)

    # ── labro init ────────────────────────────────────────────────────────────
    init_parser = subparsers.add_parser(
        "init",
        help="Create required GitHub labels for all configured projects",
    )
    init_parser.add_argument(
        "--project",
        metavar="NAME",
        default=None,
        help="Init only this project",
    )
    init_parser.set_defaults(func=_cmd_init)

    # ── labro check ───────────────────────────────────────────────────────────
    check_parser = subparsers.add_parser(
        "check",
        help="Pre-flight health check: config, env vars, labels, collaborator",
    )
    check_parser.add_argument(
        "--project",
        metavar="NAME",
        default=None,
        help="Check only this project",
    )
    check_parser.set_defaults(func=_cmd_check)

    # ── labro review ──────────────────────────────────────────────────────────
    review_parser = subparsers.add_parser(
        "review",
        help="Print tabular run history from SQLite",
    )
    review_parser.add_argument(
        "--db-path",
        type=Path,
        default=_default_db_path(),
        metavar="PATH",
    )
    review_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        metavar="N",
        help="Maximum number of runs to show (default: 20)",
    )
    review_parser.add_argument(
        "--project",
        metavar="NAME",
        default=None,
    )
    review_parser.add_argument(
        "--outcome",
        choices=["success", "failure", "partial", "skipped"],
        default=None,
    )
    review_parser.set_defaults(func=_cmd_review)

    # ── labro list-locks ──────────────────────────────────────────────────────
    list_locks_parser = subparsers.add_parser(
        "list-locks",
        help="Show currently held project locks with age",
    )
    list_locks_parser.add_argument(
        "--db-path",
        type=Path,
        default=_default_db_path(),
        metavar="PATH",
    )
    list_locks_parser.set_defaults(func=_cmd_list_locks)

    # ── labro unlock ──────────────────────────────────────────────────────────
    unlock_parser = subparsers.add_parser(
        "unlock",
        help="Manually release a stale project lock",
    )
    unlock_parser.add_argument(
        "project",
        help="Name of the project whose lock to release",
    )
    unlock_parser.add_argument(
        "--db-path",
        type=Path,
        default=_default_db_path(),
        metavar="PATH",
    )
    unlock_parser.set_defaults(func=_cmd_unlock)

    return parser


def main() -> None:
    """Entry point for the ``labro`` CLI."""
    log_fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    logging.basicConfig(level=logging.INFO, format=log_fmt)

    log_path = _default_log_path()
    if log_path.parent.exists():
        fh = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=5 * 1024 * 1024,  # 5 MB
            backupCount=5,
        )
        fh.setFormatter(logging.Formatter(log_fmt))
        # Replace the stderr StreamHandler — cron redirects stderr to the same
        # file, so keeping both would double every log line.
        root = logging.getLogger()
        root.handlers = [fh]

    parser = _build_parser()
    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
