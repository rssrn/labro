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
import contextvars
import json
import logging
import logging.handlers
import os
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import labro.logger as logger_mod
import labro.metrics as metrics_mod
import labro.post_run as post_run_mod
import labro.signals as signals_mod
import labro.store as store_mod
from labro.agents.base import AgentOutputError, AgentTimeoutError
from labro.agents.registry import get_agent
from labro.config.loader import ConfigError, load_config, referenced_agents, required_env_vars
from labro.config.schema import (
    GhAuthorSource,
    GhLabelSource,
    LabroConfig,
    PermittedAction,
    ProjectConfig,
)
from labro.models import AgentConfig, AgentResult
from labro.picker import pick
from labro.prompt_builder import build_prompt
from labro.repo import prepare_repo, preserve_wip

_log = logging.getLogger(__name__)

# Per-run context (project + short run_id) injected into every log line so
# concurrent cron runs sharing /data/labro.log can be told apart. Empty until a
# live run sets it via _set_run_context.
_run_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("run_ctx", default="")


class _RunContextFilter(logging.Filter):
    """Attach the current run context to every record as ``run_ctx``.

    @author Claude Opus 4.8 Anthropic
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.run_ctx = _run_ctx.get()
        return True


class _UTCFormatter(logging.Formatter):
    """Formatter that renders timestamps in UTC to match the SQLite run records.

    @author Claude Opus 4.8 Anthropic
    """

    converter = staticmethod(time.gmtime)
    default_msec_format = "%s,%03dZ"


def _set_run_context(project: str, run_id: str) -> None:
    """Set the log prefix for the current run (e.g. ``[newschart 237f824e]``)."""
    _run_ctx.set(f"[{project} {run_id[:8]}] ")


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

    # GitHub App: generate an installation token before any gh CLI calls
    if config.github_app_id is not None:
        import labro.github_app as gh_app_mod

        try:
            gh_token = gh_app_mod.get_installation_token(
                config.github_app_id,
                gh_app_mod.resolve_private_key_pem(),
                project.repo,
            )
            os.environ["GH_TOKEN"] = gh_token
        except Exception as exc:
            print(f"error: GitHub App authentication failed: {exc}", file=sys.stderr)
            return 1

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
    print(f"  slug      : {agent_cfg.slug}")
    print(f"  provider  : {agent_cfg.provider}")
    print(f"  model     : {agent_cfg.model}")
    print(f"  effort    : {agent_cfg.effort}")
    print(f"  max_turns : {agent_cfg.max_turns}")
    print(f"  timeout_s : {agent_cfg.timeout_s}")
    if agent_cfg.fallback_slugs:
        print(f"  fallbacks : {', '.join(agent_cfg.fallback_slugs)}")

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
        _log.info("run skipped: harness disabled (LABRO_DISABLED flag present)")
        return 0

    # Open database
    conn = store_mod.open_db(db_path)
    lock_timeout_s = (
        project.timeout_s if project.timeout_s is not None else config.defaults.timeout_s
    )

    # Acquire run lock
    if not store_mod.acquire_lock(conn, project_name, lock_timeout_s):
        _log.info("run skipped: run in progress for project %r", project_name)
        conn.close()
        return 0

    run_id = str(uuid.uuid4())
    started_at = _now_utc()
    run_started = time.monotonic()
    _set_run_context(project_name, run_id)
    _log.info("run start: repo=%s config=%s", project.repo, config_path)

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
                _log.info("%s", reason)
                return 0

        # ── GitHub App: generate per-run installation token ────────────────────
        # Must happen before pick() — the gh CLI needs GH_TOKEN to list issues.
        # Uses project.repo (known at this point) rather than task.repo.
        bot_identity: tuple[str, str] | None = None
        if config.github_app_id is not None:
            import labro.github_app as gh_app_mod

            app_name = config.github_app_name
            if app_name is None:
                raise RuntimeError("github_app_id set without github_app_name")
            try:
                gh_token = gh_app_mod.get_installation_token(
                    config.github_app_id,
                    gh_app_mod.resolve_private_key_pem(),
                    project.repo,
                )
                os.environ["GH_TOKEN"] = gh_token
                bot_identity = (
                    f"{app_name}[bot]",
                    f"{config.github_app_id}+{app_name}[bot]@users.noreply.github.com",
                )
            except Exception as exc:
                ended_at = _now_utc()
                logger_mod.write_run(
                    conn,
                    run_id=run_id,
                    project=project_name,
                    task=None,
                    agent_cfg=None,
                    agent_result=None,
                    outcome="failure",
                    failure_reason=f"github_app_auth_failed: {exc}",
                    started_at=started_at,
                    ended_at=ended_at,
                )
                _log.error("GitHub App authentication failed for %s: %s", project.repo, exc)
                return 1

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
            _log.info("run skipped: no eligible task found for project %r", project_name)
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

        # ── Pre-run comment ────────────────────────────────────────────────────
        pre_run_handle = post_run_mod.pre_run(task, agent_cfg)

        # ── Invoke agent (with model fallback) ─────────────────────────────────
        _configs_to_try = [agent_cfg] + [
            AgentConfig.from_slug(
                s,
                max_turns=agent_cfg.max_turns,
                timeout_s=agent_cfg.timeout_s,
                permitted_actions=agent_cfg.permitted_actions,
            )
            for s in agent_cfg.fallback_slugs
        ]
        failed_attempts: list[dict[str, str]] = []

        agent_result: AgentResult | None = None
        outcome = "failure"
        failure_reason: str | None = None

        for _i, _attempt_cfg in enumerate(_configs_to_try):
            _attempt_cfg.cwd = repo_path
            item_ref = (
                f"{task.item_type} #{task.item_number}"
                if task.item_number is not None
                else "(no item)"
            )
            _log.info(
                "invoking agent %s (slug=%s) on %s %s",
                _attempt_cfg.agent,
                _attempt_cfg.slug,
                task.repo,
                item_ref,
            )
            try:
                agent_result = get_agent(_attempt_cfg.agent).invoke(prompt, _attempt_cfg)
                outcome = agent_result.outcome
                failure_reason = agent_result.failure_reason
                if failure_reason == "session_limit_hit":
                    _next_configs = _configs_to_try[_i + 1 :]
                    if _next_configs:
                        reason = "session_limit_hit"
                        failed_attempts.append({"slug": _attempt_cfg.slug, "reason": reason})
                        _log.warning(
                            "agent %s hit session/quota limit; trying next model",
                            _attempt_cfg.slug,
                        )
                        if pre_run_handle is not None:
                            post_run_mod.append_fallback_note(
                                pre_run_handle,
                                failed_slug=_attempt_cfg.slug,
                                reason=reason,
                                next_slug=_next_configs[0].slug,
                            )
                        agent_result = None
                        continue
                agent_cfg = _attempt_cfg  # winning attempt
                break
            except AgentTimeoutError:
                reason = "timeout"
                failed_attempts.append({"slug": _attempt_cfg.slug, "reason": reason})
                _log.warning("agent %s timed out; trying next model", _attempt_cfg.slug)
                _next_configs = _configs_to_try[_i + 1 :]
                if pre_run_handle is not None and _next_configs:
                    post_run_mod.append_fallback_note(
                        pre_run_handle,
                        failed_slug=_attempt_cfg.slug,
                        reason=reason,
                        next_slug=_next_configs[0].slug,
                    )
            except AgentOutputError as exc:
                reason = str(exc)
                failed_attempts.append({"slug": _attempt_cfg.slug, "reason": reason})
                _log.warning("agent %s output error: %s; trying next", _attempt_cfg.slug, exc)
                _next_configs = _configs_to_try[_i + 1 :]
                if pre_run_handle is not None and _next_configs:
                    post_run_mod.append_fallback_note(
                        pre_run_handle,
                        failed_slug=_attempt_cfg.slug,
                        reason=reason,
                        next_slug=_next_configs[0].slug,
                    )

        # If every attempt failed with an exception, update agent_cfg to the last
        # attempt so the run record reflects the actual last model tried.
        if agent_result is None and failed_attempts:
            agent_cfg = _configs_to_try[-1]
            failure_reason = failed_attempts[-1]["reason"]

        fallback_attempts_json = json.dumps(failed_attempts) if failed_attempts else None

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
                wip_branch_url = preserve_wip(
                    repo_path, task.repo, run_id, bot_identity=bot_identity
                )

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
        # For proactive-improvement: use the agent-updated issue title on success
        # (the agent is prompted to rename the issue), or the tidied perspective
        # name (e.g. "Red Team") on failure/partial.
        proactive_task_description: str | None = None
        if task is not None and task.source == "proactive-improvement":
            if outcome == "success" and task.item_number is not None:
                proactive_task_description = _fetch_issue_title(task.item_number, task.repo)
            if proactive_task_description is None and task.chosen_perspective:
                proactive_task_description = task.chosen_perspective.replace("-", " ").title()

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
            fallback_attempts=fallback_attempts_json,
            task_description_override=proactive_task_description,
        )

        dur_s = time.monotonic() - run_started
        metrics_mod.push_run(
            project=project_name,
            outcome=outcome,
            duration_s=dur_s,
            started_at_ts=time.time() - dur_s,
        )

        parts = [f"run complete: outcome={outcome}", f"dur={dur_s:.0f}s"]
        ar = agent_result
        if ar is not None:
            if ar.num_turns:
                parts.append(f"turns={ar.num_turns}")
            if ar.total_cost_usd:
                parts.append(f"cost=${ar.total_cost_usd:.4f}")
            total_tokens = (
                ar.input_tokens + ar.output_tokens + ar.cache_read_tokens + ar.cache_write_tokens
            )
            if total_tokens:
                parts.append(f"tokens={total_tokens:,}")
        if outcome != "success" and failure_reason:
            parts.append(f"reason={failure_reason}")
        if ar is not None and ar.summary:
            parts.append(f'"{ar.summary.splitlines()[0]}"')
        msg = " ".join(parts)
        if outcome == "success":
            _log.info("%s", msg)
        else:
            _log.warning("%s", msg)
        _log.info("run complete: outcome=%r run_id=%s", outcome, run_id)
        return 0 if outcome == "success" else 1

    finally:
        store_mod.release_lock(conn, project_name)
        conn.close()


# ── Operator helpers ───────────────────────────────────────────────────────────


def _run_gh(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a gh CLI command (list-form, shell=False) and return the result.

    @author Claude Sonnet 4.6 Anthropic
    """
    return subprocess.run(cmd, capture_output=True, text=True, shell=False)


def _fetch_issue_title(issue_number: int, repo: str) -> str | None:
    """Return the current title of a GitHub issue, or None on any error.

    @author Claude Sonnet 4.6 Anthropic
    """
    try:
        result = subprocess.run(
            ["gh", "api", f"repos/{repo}/issues/{issue_number}"],
            capture_output=True,
            text=True,
            check=True,
            shell=False,
        )
        title: str | None = json.loads(result.stdout).get("title")
        return title
    except (subprocess.CalledProcessError, json.JSONDecodeError, KeyError, ValueError):
        return None


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
        elif isinstance(source, GhAuthorSource):
            for ar in source.author_rules:
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


def _cmd_check(args: argparse.Namespace) -> int:
    """Pre-flight health check: config, env vars, labels, collaborator.

    @author Claude Sonnet 4.6 Anthropic
    """
    try:
        config = load_config(args.config, check_env=False)
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

    # Per-agent auth validation
    try:
        _ref_agents = referenced_agents(config)
    except Exception:
        _ref_agents = set()
    for _agent_id in sorted(_ref_agents):
        try:
            _agent = get_agent(_agent_id)
        except ValueError as exc:
            results.append(("FAIL", str(exc)))
            continue
        results.append(_agent.validate_auth())

    # GitHub auth check
    if config.github_app_id is not None:
        import labro.github_app as gh_app_mod

        key_var = (
            "GH_APP_PRIVATE_KEY_BASE64"
            if os.environ.get("GH_APP_PRIVATE_KEY_BASE64")
            else "GH_APP_PRIVATE_KEY"
        )
        results.append(("OK  ", f"env var {key_var}"))
        # Try to get an installation token for the first enabled project's repo
        enabled = [p for p in config.projects if p.enabled]
        if args.project:
            enabled = [p for p in enabled if p.name == args.project]
        if enabled:
            test_repo = enabled[0].repo
            try:
                gh_token = gh_app_mod.get_installation_token(
                    config.github_app_id,
                    gh_app_mod.resolve_private_key_pem(),
                    test_repo,
                )
                os.environ["GH_TOKEN"] = gh_token
                results.append(("OK  ", f"github_app installation token obtained for {test_repo}"))
            except Exception as exc:
                results.append(("FAIL", f"github_app token failed for {test_repo}: {exc}"))
    else:
        gh_auth = _run_gh(["gh", "auth", "status"])
        if gh_auth.returncode == 0:
            results.append(("OK  ", "gh auth status: authenticated"))
        else:
            msg = gh_auth.stderr.strip() or "not authenticated"
            results.append(("FAIL", f"gh auth status: {msg}"))

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


# ── labro collect-signals ────────────────────────────────────────────────────────


def _cmd_collect_signals(args: argparse.Namespace) -> int:
    """Back-fill engagement signals (outcome, reactions, follow-up commits) for
    ``items_touched`` rows that have never been collected, or re-collect open
    items that have gone stale.

    Returns 0 even when some items error — partial success is normal.

    @author Claude Sonnet 4.6 Anthropic
    """
    db_path: Path = args.db_path
    dry_run: bool = args.dry_run
    stale_days: int = args.stale_days

    # Derive bot identity and App credentials from config.
    bot_username: str | None = None
    github_app_id: int | None = None
    config_path: Path = args.config
    try:
        config = load_config(config_path, check_env=False)
        if config.github_app_name is not None:
            bot_username = f"{config.github_app_name}[bot]"
        if config.github_app_id is not None:
            github_app_id = config.github_app_id
    except ConfigError:
        pass  # no config → no bot identity → legacy reaction counting

    if not db_path.exists():
        print(f"No database at {db_path}.")
        return 0

    conn = store_mod.open_db(db_path)
    try:
        rows = store_mod.get_items_for_signal_collection(conn, stale_days=stale_days)
    except Exception:
        conn.close()
        raise

    if not rows:
        print("No items require signal collection.")
        conn.close()
        return 0

    updated = 0
    errors = 0
    _token_cache: dict[str, str] = {}
    for row in rows:
        repo: str = row["repo"]
        item_type: str = row["item_type"]
        item_number: int = row["item_number"]
        started_at: str = row["started_at"]

        # Ensure GH_TOKEN is set for gh api calls; GitHub App installs have no
        # ambient token so we generate one per repo (cached for the run).
        if github_app_id is not None:
            import labro.github_app as gh_app_mod

            if repo not in _token_cache:
                _token_cache[repo] = gh_app_mod.get_installation_token(
                    github_app_id,
                    gh_app_mod.resolve_private_key_pem(),
                    repo,
                )
            os.environ["GH_TOKEN"] = _token_cache[repo]

        try:
            signals = signals_mod.collect(
                repo, item_type, item_number, started_at, bot_username=bot_username
            )
        except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
            _log.warning("collect-signals error %s#%d: %s", repo, item_number, exc)
            errors += 1
            continue

        collected_at = _now_utc()
        if not dry_run:
            store_mod.update_item_signals(
                conn,
                repo,
                item_type,
                item_number,
                outcome_state=signals.outcome_state,
                follow_up_commits=signals.follow_up_commits,
                thumbs_up=signals.thumbs_up,
                thumbs_down=signals.thumbs_down,
                collected_at=collected_at,
            )
        updated += 1

        thumbs_str = f"\U0001f44d{signals.thumbs_up} \U0001f44e{signals.thumbs_down}"
        _log.info(
            "collect-signals %s#%d \u2192 %s %s",
            repo,
            item_number,
            signals.outcome_state or "-",
            thumbs_str,
        )

    print(f"{updated} updated, {errors} errors")
    conn.close()
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
        config = load_config(config_path, check_env=False)
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

    if config.dashboard.enabled:
        lines.append("")
        lines.append("# Dashboard DB snapshot upload")
        lines.append(
            f"{config.dashboard.cron}   root  . /etc/labro-env;"
            f" labro publish-db  >> {log_path}  2>&1"
        )

    if config.signals.enabled:
        lines.append("")
        lines.append("# Signal collection (back-fill outcome signals)")
        lines.append(
            f"{config.signals.cron}   root  . /etc/labro-env;"
            f" labro collect-signals  >> {log_path}  2>&1"
        )

    print("\n".join(lines))
    return 0


# ── labro publish-db ───────────────────────────────────────────────────────────


def _cmd_publish_db(args: argparse.Namespace) -> int:
    """Snapshot labro.db via VACUUM INTO and upload the snapshot + manifest to R2.

    @author Claude Sonnet 4.6 Anthropic
    """
    import hashlib
    import json

    config_path: Path = args.config
    db_path: Path = args.db_path
    snapshot_path_override: Path | None = args.snapshot_path
    dry_run: bool = args.dry_run

    try:
        config = load_config(config_path)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if not config.dashboard.enabled:
        _log.warning("publish-db: dashboard.enabled = false in config; nothing to do")
        return 0

    if not dry_run:
        r2_missing = [
            v
            for v in ("R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_ACCOUNT_ID", "R2_BUCKET")
            if not os.environ.get(v)
        ]
        if r2_missing:
            print(
                f"error: Missing required environment variable(s): {', '.join(r2_missing)}",
                file=sys.stderr,
            )
            return 1

    if not db_path.exists():
        _log.warning("publish-db: database not found at %s; nothing to do", db_path)
        return 0

    # Build temp snapshot path (or use override)
    if snapshot_path_override is not None:
        snapshot_path = snapshot_path_override
        cleanup_snapshot = False
    else:
        snapshot_path = db_path.parent / f".labro-snapshot-{os.getpid()}.db"
        cleanup_snapshot = True

    # Remove stale snapshot if present (VACUUM INTO requires the target not to exist)
    if snapshot_path.exists():
        snapshot_path.unlink()

    try:
        import sqlite3

        conn = store_mod.open_db(db_path)
        try:
            project_rows = [(p.name, p.name_short, p.repo) for p in config.projects]
            store_mod.upsert_projects(conn, project_rows)
            # Bound parameter avoids bandit B608 (SQL injection via f-string)
            conn.execute("VACUUM INTO ?", (str(snapshot_path),))
        finally:
            conn.close()

        # Hash the snapshot for content-addressed key and manifest
        hasher = hashlib.sha256()
        size_bytes = snapshot_path.stat().st_size
        with open(snapshot_path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        content_hash = hasher.hexdigest()

        key_prefix = config.dashboard.key_prefix
        db_filename = f"labro-{content_hash[:16]}.db"
        db_key = f"{key_prefix}db/{db_filename}"

        # Row count from snapshot
        snap_conn = sqlite3.connect(str(snapshot_path))
        try:
            row_count: int = snap_conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        finally:
            snap_conn.close()

        manifest_dict: dict[str, object] = {
            "schema_version": 1,
            "db_filename": f"db/{db_filename}",
            "content_hash": content_hash,
            "generated_at": _now_utc(),
            "size_bytes": size_bytes,
            "row_count": row_count,
        }
        if config.dashboard.title is not None:
            manifest_dict["title"] = config.dashboard.title
        manifest_bytes = json.dumps(manifest_dict, indent=2).encode()

        if dry_run:
            print(f"snapshot: {snapshot_path}")
            print(f"db_key:   {key_prefix}db/{db_filename}")
            print(f"manifest: {json.dumps(manifest_dict, indent=2)}")
            return 0

        # Resolve credentials
        import labro.r2 as r2_mod

        try:
            creds = r2_mod.credentials_from_env()
            bucket = os.environ["R2_BUCKET"]
        except KeyError as exc:
            print(f"error: missing R2 credential env var: {exc}", file=sys.stderr)
            return 1

        # Override endpoint from config if set (used in tests / custom deployments)
        if config.dashboard.endpoint is not None:
            from dataclasses import replace

            creds = replace(creds, endpoint=config.dashboard.endpoint)

        try:
            # Upload DB first — manifest must never point at a missing object
            r2_mod.upload_snapshot(creds, db_path=str(snapshot_path), db_key=db_key, bucket=bucket)
            r2_mod.upload_manifest(creds, manifest=manifest_bytes, bucket=bucket)
        except RuntimeError as exc:
            print(f"error: upload failed: {exc}", file=sys.stderr)
            return 1

        _log.info(
            "publish-db: uploaded %s (%d rows, %.1f KB) → %s",
            db_key,
            row_count,
            size_bytes / 1024,
            bucket,
        )
        return 0

    finally:
        if cleanup_snapshot and snapshot_path.exists():
            snapshot_path.unlink(missing_ok=True)


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
        "--version",
        action="version",
        version=f"%(prog)s {__import__('labro').__version__}",
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

    # ── labro publish-db ──────────────────────────────────────────────────────
    publish_db_parser = subparsers.add_parser(
        "publish-db",
        help="Snapshot labro.db and upload to R2 for the metrics dashboard",
    )
    publish_db_parser.add_argument(
        "--db-path",
        type=Path,
        default=_default_db_path(),
        metavar="PATH",
        help="Path to the SQLite database (default: $LABRO_DB_PATH or /data/labro.db)",
    )
    publish_db_parser.add_argument(
        "--snapshot-path",
        type=Path,
        default=None,
        metavar="PATH",
        help="Write the VACUUM snapshot here instead of a temp file (kept after upload)",
    )
    publish_db_parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print snapshot path + manifest JSON without uploading",
    )
    publish_db_parser.set_defaults(func=_cmd_publish_db)

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

    # ── labro collect-signals ───────────────────────────────────────────────
    collect_signals_parser = subparsers.add_parser(
        "collect-signals",
        help="Back-fill engagement signals for items_touched rows via the GitHub API",
    )
    collect_signals_parser.add_argument(
        "--db-path",
        type=Path,
        default=_default_db_path(),
        metavar="PATH",
        help="Path to the SQLite database (default: $LABRO_DB_PATH or /data/labro.db)",
    )
    collect_signals_parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print what would be written without modifying the database",
    )
    collect_signals_parser.add_argument(
        "--stale-days",
        type=int,
        default=7,
        metavar="N",
        help=(
            "Re-collect open items not refreshed in N days (default: 7)."
            " Set to 0 to collect only uncollected items."
        ),
    )
    collect_signals_parser.set_defaults(func=_cmd_collect_signals)

    return parser


def main() -> None:
    """Entry point for the ``labro`` CLI."""
    log_fmt = "%(asctime)s %(levelname)s %(run_ctx)s%(name)s - %(message)s"
    formatter = _UTCFormatter(log_fmt)
    ctx_filter = _RunContextFilter()

    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    stream.addFilter(ctx_filter)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers = [stream]

    log_path = _default_log_path()
    if log_path.parent.exists():
        fh = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=5 * 1024 * 1024,  # 5 MB
            backupCount=5,
        )
        fh.setFormatter(formatter)
        fh.addFilter(ctx_filter)
        # Replace the stderr StreamHandler — cron redirects stderr to the same
        # file, so keeping both would double every log line.
        root.handlers = [fh]

    parser = _build_parser()
    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
