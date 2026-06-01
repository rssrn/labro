"""Tests for the live (non-dry-run) path of cli.py (M2 scope).

All tests target ``_cmd_run_live`` directly to avoid the argparse layer.
The SQLite database is opened in-memory where possible; the LABRO_DISABLED
check uses a real temp file via pytest's ``tmp_path`` fixture.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import labro.store as store_mod
from labro.cli import _cmd_run_live
from labro.config.schema import (
    DefaultsConfig,
    DigestConfig,
    LabelRule,
    LabroConfig,
    PermittedAction,
    ProjectConfig,
)
from labro.config.schema import (
    GhLabelSource as GhLabelSourceConfig,
)
from labro.models import AgentConfig, AgentResult, Task

# ── Shared helpers ─────────────────────────────────────────────────────────────


def _make_config(
    project_name: str = "labro",
    daily_budget_usd: float | None = None,
    timeout_s: int | None = None,
    claude_assignee: str | None = None,
) -> LabroConfig:
    """Build a minimal ``LabroConfig`` with a single project."""
    label_rule = LabelRule(label="ai-dev", done_label="ai-dev-done")
    src = GhLabelSourceConfig(type="gh-label", label_rules=[label_rule])
    project = ProjectConfig(
        name=project_name,
        repo="org/repo",
        cron="0 * * * *",
        task_sources=[src],
        daily_budget_usd=daily_budget_usd,
        timeout_s=timeout_s,
        permitted_actions=[PermittedAction.COMMENT_ON_ISSUE],
    )
    return LabroConfig(
        digest=DigestConfig(enabled=False),
        defaults=DefaultsConfig(model="anthropic/claude-opus-4-7", max_turns=20, timeout_s=600),
        projects=[project],
        claude_assignee=claude_assignee,
    )


def _make_task(project_name: str = "labro") -> Task:
    return Task(
        task_id="test-task-id",
        source="gh-label",
        description="#1: Fix something\n\nBody text.",
        permitted_actions=[PermittedAction.COMMENT_ON_ISSUE],
        repo="org/repo",
        item_type="issue",
        item_number=1,
        item_url="https://github.com/org/repo/issues/1",
        source_label="ai-dev",
        done_label="ai-dev-done",
        grafana_rule_uid=None,
    )


def _make_agent_cfg() -> AgentConfig:
    return AgentConfig(
        agent="claude-code",
        model="anthropic/claude-opus-4-7",
        max_turns=20,
        timeout_s=600,
    )


def _make_agent_result(outcome: str = "success") -> AgentResult:
    return AgentResult(
        outcome=outcome,
        summary="Task completed.",
        actions_taken=["commented on issue #1"],
        is_error=False,
        num_turns=3,
        total_cost_usd=0.02,
        duration_ms=5000,
    )


def _open_mem_db() -> sqlite3.Connection:
    """Open a fresh in-memory database with the Labro schema applied."""
    return store_mod.open_db(":memory:")


# ── Tests ──────────────────────────────────────────────────────────────────────


def test_labro_disabled_skips_without_lock(tmp_path: Path) -> None:
    """If LABRO_DISABLED exists, the run exits before acquiring a lock."""
    db_path = tmp_path / "labro.db"
    repos_dir = tmp_path / "repos"
    disabled_flag = tmp_path / "LABRO_DISABLED"
    disabled_flag.touch()

    config = _make_config()

    with (
        patch("labro.cli.load_config", return_value=config),
        patch("labro.cli.store_mod.open_db") as mock_open_db,
        patch("labro.cli.store_mod.acquire_lock") as mock_acquire,
    ):
        result = _cmd_run_live(
            config_path=Path("labro.toml"),
            project_name="labro",
            db_path=db_path,
            repos_dir=repos_dir,
        )

    assert result == 0
    mock_open_db.assert_not_called()
    mock_acquire.assert_not_called()


def test_lock_contention_exits_cleanly(tmp_path: Path) -> None:
    """If acquire_lock returns False, exit 0 with no run record written."""
    db_path = tmp_path / "labro.db"
    repos_dir = tmp_path / "repos"
    # No LABRO_DISABLED — only lock contention
    conn = _open_mem_db()
    config = _make_config()

    with (
        patch("labro.cli.load_config", return_value=config),
        patch("labro.cli.store_mod.open_db", return_value=conn),
        patch("labro.cli.store_mod.acquire_lock", return_value=False),
        patch("labro.cli.logger_mod.write_run") as mock_write,
    ):
        result = _cmd_run_live(
            config_path=Path("labro.toml"),
            project_name="labro",
            db_path=db_path,
            repos_dir=repos_dir,
        )

    assert result == 0
    mock_write.assert_not_called()

    conn.close()


def test_budget_exceeded_skips_after_lock(tmp_path: Path) -> None:
    """Budget exceeded → skipped run record written; lock acquired and released."""
    db_path = tmp_path / "labro.db"
    repos_dir = tmp_path / "repos"
    conn = _open_mem_db()
    config = _make_config(daily_budget_usd=1.00)

    with (
        patch("labro.cli.load_config", return_value=config),
        patch("labro.cli.store_mod.open_db", return_value=conn),
        patch("labro.cli.store_mod.acquire_lock", return_value=True),
        patch("labro.cli.store_mod.get_daily_spend", return_value=1.50),
        patch("labro.cli.store_mod.release_lock") as mock_release,
        patch("labro.cli.logger_mod.write_run") as mock_write,
    ):
        result = _cmd_run_live(
            config_path=Path("labro.toml"),
            project_name="labro",
            db_path=db_path,
            repos_dir=repos_dir,
        )

    assert result == 0
    # Lock must be released even on budget skip
    mock_release.assert_called_once()
    # Skipped run record must be written
    mock_write.assert_called_once()
    call_kwargs: dict[str, Any] = mock_write.call_args.kwargs
    assert call_kwargs["outcome"] == "skipped"
    assert call_kwargs["failure_reason"] is not None
    assert "budget" in call_kwargs["failure_reason"]
    assert call_kwargs["task"] is None

    conn.close()


def test_no_task_skips_cleanly(tmp_path: Path) -> None:
    """Picker returns None → skipped run record written with failure_reason; lock released."""
    db_path = tmp_path / "labro.db"
    repos_dir = tmp_path / "repos"
    conn = _open_mem_db()
    config = _make_config()

    with (
        patch("labro.cli.load_config", return_value=config),
        patch("labro.cli.store_mod.open_db", return_value=conn),
        patch("labro.cli.store_mod.acquire_lock", return_value=True),
        patch("labro.cli.store_mod.release_lock") as mock_release,
        patch("labro.cli.pick", return_value=(None, None)),
        patch("labro.cli.logger_mod.write_run") as mock_write,
    ):
        result = _cmd_run_live(
            config_path=Path("labro.toml"),
            project_name="labro",
            db_path=db_path,
            repos_dir=repos_dir,
        )

    assert result == 0
    mock_release.assert_called_once()
    mock_write.assert_called_once()
    call_kwargs = mock_write.call_args.kwargs
    assert call_kwargs["outcome"] == "skipped"
    assert "no task" in (call_kwargs["failure_reason"] or "").lower()
    assert call_kwargs["task"] is None
    assert call_kwargs["agent_cfg"] is None

    conn.close()


def test_successful_agent_run_writes_success_record(tmp_path: Path) -> None:
    """Full run with successful agent result writes outcome='success' to SQLite."""
    db_path = tmp_path / "labro.db"
    repos_dir = tmp_path / "repos"
    conn = _open_mem_db()
    config = _make_config()
    task = _make_task()
    agent_cfg = _make_agent_cfg()
    agent_result = _make_agent_result(outcome="success")

    with (
        patch("labro.cli.load_config", return_value=config),
        patch("labro.cli.store_mod.open_db", return_value=conn),
        patch("labro.cli.store_mod.acquire_lock", return_value=True),
        patch("labro.cli.store_mod.release_lock"),
        patch("labro.cli.pick", return_value=(task, agent_cfg)),
        patch("labro.cli.prepare_repo", return_value=(tmp_path / "repos" / "org" / "repo", None)),
        patch("labro.cli.ClaudeCodeAgent") as MockAgent,
        patch("labro.cli.logger_mod.write_run") as mock_write,
    ):
        mock_instance = MagicMock()
        mock_instance.invoke.return_value = agent_result
        MockAgent.return_value = mock_instance

        result = _cmd_run_live(
            config_path=Path("labro.toml"),
            project_name="labro",
            db_path=db_path,
            repos_dir=repos_dir,
        )

    assert result == 0
    mock_write.assert_called_once()
    call_kwargs = mock_write.call_args.kwargs
    assert call_kwargs["outcome"] == "success"
    assert call_kwargs["task"] is task
    assert call_kwargs["agent_result"] is agent_result

    conn.close()


def test_partial_outcome_stored_as_partial(tmp_path: Path) -> None:
    """AgentResult.outcome='partial' is stored as outcome='partial' in the runs table."""
    db_path = tmp_path / "labro.db"
    repos_dir = tmp_path / "repos"
    conn = _open_mem_db()
    config = _make_config()
    task = _make_task()
    agent_cfg = _make_agent_cfg()
    agent_result = _make_agent_result(outcome="partial")

    with (
        patch("labro.cli.load_config", return_value=config),
        patch("labro.cli.store_mod.open_db", return_value=conn),
        patch("labro.cli.store_mod.acquire_lock", return_value=True),
        patch("labro.cli.store_mod.release_lock"),
        patch("labro.cli.pick", return_value=(task, agent_cfg)),
        patch("labro.cli.prepare_repo", return_value=(tmp_path / "repos" / "org" / "repo", None)),
        patch("labro.cli.preserve_wip", return_value=None),
        patch("labro.cli.ClaudeCodeAgent") as MockAgent,
        patch("labro.cli.logger_mod.write_run") as mock_write,
    ):
        mock_instance = MagicMock()
        mock_instance.invoke.return_value = agent_result
        MockAgent.return_value = mock_instance

        result = _cmd_run_live(
            config_path=Path("labro.toml"),
            project_name="labro",
            db_path=db_path,
            repos_dir=repos_dir,
        )

    assert result == 1  # non-success → non-zero exit
    call_kwargs = mock_write.call_args.kwargs
    assert call_kwargs["outcome"] == "partial"

    conn.close()


def test_partial_outcome_wip_preservation_attempted(tmp_path: Path) -> None:
    """On a partial outcome, preserve_wip is called and its URL passed to post_run."""
    db_path = tmp_path / "labro.db"
    repos_dir = tmp_path / "repos"
    repo_path = tmp_path / "repos" / "org" / "repo"
    conn = _open_mem_db()
    config = _make_config()
    task = _make_task()
    agent_cfg = _make_agent_cfg()
    agent_result = _make_agent_result(outcome="partial")
    wip_url = "https://github.com/org/repo/tree/labro-wip/run-123"

    with (
        patch("labro.cli.load_config", return_value=config),
        patch("labro.cli.store_mod.open_db", return_value=conn),
        patch("labro.cli.store_mod.acquire_lock", return_value=True),
        patch("labro.cli.store_mod.release_lock"),
        patch("labro.cli.pick", return_value=(task, agent_cfg)),
        patch("labro.cli.prepare_repo", return_value=(repo_path, None)),
        patch("labro.cli.preserve_wip", return_value=wip_url) as mock_preserve,
        patch("labro.cli.ClaudeCodeAgent") as MockAgent,
        patch("labro.cli.logger_mod.write_run"),
        patch("labro.cli.post_run_mod.post_run") as mock_post_run,
    ):
        mock_instance = MockAgent.return_value
        mock_instance.invoke.return_value = agent_result

        _cmd_run_live(
            config_path=Path("labro.toml"),
            project_name="labro",
            db_path=db_path,
            repos_dir=repos_dir,
        )

    mock_preserve.assert_called_once_with(repo_path, "org/repo", mock_preserve.call_args[0][2])
    call_kwargs = mock_post_run.call_args.kwargs
    assert call_kwargs["wip_branch_url"] == wip_url

    conn.close()


def test_runner_timeout_stored_as_failure(tmp_path: Path) -> None:
    """RunnerTimeoutError results in outcome='failure' with failure_reason='timeout'."""
    from labro.runner import RunnerTimeoutError

    db_path = tmp_path / "labro.db"
    repos_dir = tmp_path / "repos"
    conn = _open_mem_db()
    config = _make_config()
    task = _make_task()
    agent_cfg = _make_agent_cfg()

    with (
        patch("labro.cli.load_config", return_value=config),
        patch("labro.cli.store_mod.open_db", return_value=conn),
        patch("labro.cli.store_mod.acquire_lock", return_value=True),
        patch("labro.cli.store_mod.release_lock"),
        patch("labro.cli.pick", return_value=(task, agent_cfg)),
        patch("labro.cli.prepare_repo", return_value=(tmp_path / "repos" / "org" / "repo", None)),
        patch("labro.cli.preserve_wip", return_value=None),
        patch("labro.cli.ClaudeCodeAgent") as MockAgent,
        patch("labro.cli.logger_mod.write_run") as mock_write,
    ):
        mock_instance = MagicMock()
        mock_instance.invoke.side_effect = RunnerTimeoutError("timed out")
        MockAgent.return_value = mock_instance

        result = _cmd_run_live(
            config_path=Path("labro.toml"),
            project_name="labro",
            db_path=db_path,
            repos_dir=repos_dir,
        )

    assert result == 1
    call_kwargs = mock_write.call_args.kwargs
    assert call_kwargs["outcome"] == "failure"
    assert call_kwargs["failure_reason"] == "timeout"
    assert call_kwargs["agent_result"] is None

    conn.close()


def test_lock_released_on_exception(tmp_path: Path) -> None:
    """Lock is released in ``finally`` even when an unexpected exception occurs."""
    db_path = tmp_path / "labro.db"
    repos_dir = tmp_path / "repos"
    conn = _open_mem_db()
    config = _make_config()
    task = _make_task()
    agent_cfg = _make_agent_cfg()

    with (
        patch("labro.cli.load_config", return_value=config),
        patch("labro.cli.store_mod.open_db", return_value=conn),
        patch("labro.cli.store_mod.acquire_lock", return_value=True),
        patch("labro.cli.store_mod.release_lock") as mock_release,
        patch("labro.cli.pick", return_value=(task, agent_cfg)),
        patch("labro.cli.prepare_repo", side_effect=RuntimeError("disk full")),
    ):
        with pytest.raises(RuntimeError, match="disk full"):
            _cmd_run_live(
                config_path=Path("labro.toml"),
                project_name="labro",
                db_path=db_path,
                repos_dir=repos_dir,
            )

    # The finally block must have fired and released the lock.
    mock_release.assert_called_once()

    conn.close()


def test_claude_assignee_assigned_and_restored_on_success(tmp_path: Path) -> None:
    """When claude_assignee is set, assign before agent and restore after (success path)."""
    db_path = tmp_path / "labro.db"
    repos_dir = tmp_path / "repos"
    conn = _open_mem_db()
    config = _make_config(claude_assignee="claude-code-bot")
    task = _make_task()
    agent_cfg = _make_agent_cfg()
    agent_result = _make_agent_result(outcome="success")

    with (
        patch("labro.cli.load_config", return_value=config),
        patch("labro.cli.store_mod.open_db", return_value=conn),
        patch("labro.cli.store_mod.acquire_lock", return_value=True),
        patch("labro.cli.store_mod.release_lock"),
        patch("labro.cli.pick", return_value=(task, agent_cfg)),
        patch("labro.cli.prepare_repo", return_value=(tmp_path / "repos" / "org" / "repo", None)),
        patch("labro.cli.ClaudeCodeAgent") as MockAgent,
        patch("labro.cli.logger_mod.write_run"),
        patch("labro.cli.assignee_mod.comment_assignment") as mock_comment,
        patch("labro.cli.assignee_mod.assign_claude") as mock_assign,
        patch("labro.cli.assignee_mod.restore_assignees") as mock_restore,
    ):
        calls: list[str] = []
        mock_comment.side_effect = lambda *_args, **_kwargs: calls.append("comment")
        mock_assign.side_effect = lambda *_args, **_kwargs: calls.append("assign")
        mock_instance = MockAgent.return_value
        mock_instance.invoke.return_value = agent_result

        result = _cmd_run_live(
            config_path=Path("labro.toml"),
            project_name="labro",
            db_path=db_path,
            repos_dir=repos_dir,
        )

    assert result == 0
    assert calls == ["comment", "assign"]
    mock_comment.assert_called_once_with(task, "claude-code-bot")
    mock_assign.assert_called_once_with(task, "claude-code-bot")
    mock_restore.assert_called_once_with(task, "claude-code-bot")

    conn.close()


def test_claude_assignee_restored_on_agent_failure(tmp_path: Path) -> None:
    """restore_assignees is called in finally even when the agent raises."""
    from labro.runner import RunnerTimeoutError

    db_path = tmp_path / "labro.db"
    repos_dir = tmp_path / "repos"
    conn = _open_mem_db()
    config = _make_config(claude_assignee="claude-code-bot")
    task = _make_task()
    agent_cfg = _make_agent_cfg()

    with (
        patch("labro.cli.load_config", return_value=config),
        patch("labro.cli.store_mod.open_db", return_value=conn),
        patch("labro.cli.store_mod.acquire_lock", return_value=True),
        patch("labro.cli.store_mod.release_lock"),
        patch("labro.cli.pick", return_value=(task, agent_cfg)),
        patch("labro.cli.prepare_repo", return_value=(tmp_path / "repos" / "org" / "repo", None)),
        patch("labro.cli.preserve_wip", return_value=None),
        patch("labro.cli.ClaudeCodeAgent") as MockAgent,
        patch("labro.cli.logger_mod.write_run"),
        patch("labro.cli.assignee_mod.comment_assignment"),
        patch("labro.cli.assignee_mod.assign_claude"),
        patch("labro.cli.assignee_mod.restore_assignees") as mock_restore,
    ):
        mock_instance = MockAgent.return_value
        mock_instance.invoke.side_effect = RunnerTimeoutError("timed out")

        result = _cmd_run_live(
            config_path=Path("labro.toml"),
            project_name="labro",
            db_path=db_path,
            repos_dir=repos_dir,
        )

    assert result == 1
    # restore must be called even though the agent timed out
    mock_restore.assert_called_once_with(task, "claude-code-bot")

    conn.close()


def test_wip_resume_passes_branch_to_prepare_and_prompt(tmp_path: Path) -> None:
    """When a prior partial run exists for the item, harness resumes from its WIP branch."""
    db_path = tmp_path / "labro.db"
    repos_dir = tmp_path / "repos"
    repo_path = tmp_path / "repos" / "org" / "repo"
    conn = _open_mem_db()
    config = _make_config()
    task = _make_task()
    agent_cfg = _make_agent_cfg()
    agent_result = _make_agent_result(outcome="success")
    wip_branch = "labro-wip/prior-run-uuid"
    wip_url = f"https://github.com/org/repo/tree/{wip_branch}"

    with (
        patch("labro.cli.load_config", return_value=config),
        patch("labro.cli.store_mod.open_db", return_value=conn),
        patch("labro.cli.store_mod.acquire_lock", return_value=True),
        patch("labro.cli.store_mod.release_lock"),
        patch(
            "labro.cli.store_mod.get_prior_wip_run",
            return_value=(wip_url, "Did X and Y."),
        ),
        patch("labro.cli.pick", return_value=(task, agent_cfg)),
        patch("labro.cli.prepare_repo", return_value=(repo_path, wip_branch)) as mock_prep,
        patch("labro.cli.build_prompt", return_value="prompt text") as mock_build,
        patch("labro.cli.ClaudeCodeAgent") as MockAgent,
        patch("labro.cli.logger_mod.write_run"),
        patch("labro.cli.post_run_mod.post_run") as mock_post_run,
    ):
        mock_instance = MockAgent.return_value
        mock_instance.invoke.return_value = agent_result

        result = _cmd_run_live(
            config_path=Path("labro.toml"),
            project_name="labro",
            db_path=db_path,
            repos_dir=repos_dir,
        )

    assert result == 0
    # prepare_repo must receive the WIP branch
    mock_prep.assert_called_once()
    assert mock_prep.call_args.kwargs.get("wip_branch") == wip_branch or (
        len(mock_prep.call_args.args) >= 3 and mock_prep.call_args.args[2] == wip_branch
    )
    # build_prompt must receive wip_branch and prior_summary
    mock_build.assert_called_once()
    build_kwargs = mock_build.call_args.kwargs
    assert build_kwargs.get("wip_branch") == wip_branch
    assert build_kwargs.get("prior_summary") == "Did X and Y."
    # post_run must NOT set resuming_wip (success path; wip_branch still set on success)
    mock_post_run.assert_called_once()

    conn.close()


def test_wip_branch_not_found_clears_resume_context(tmp_path: Path) -> None:
    """If WIP branch is absent on remote, agent runs from scratch (no resume context in prompt)."""
    db_path = tmp_path / "labro.db"
    repos_dir = tmp_path / "repos"
    repo_path = tmp_path / "repos" / "org" / "repo"
    conn = _open_mem_db()
    config = _make_config()
    task = _make_task()
    agent_cfg = _make_agent_cfg()
    agent_result = _make_agent_result(outcome="success")
    stale_wip_url = "https://github.com/org/repo/tree/labro-wip/stale-run-uuid"

    with (
        patch("labro.cli.load_config", return_value=config),
        patch("labro.cli.store_mod.open_db", return_value=conn),
        patch("labro.cli.store_mod.acquire_lock", return_value=True),
        patch("labro.cli.store_mod.release_lock"),
        patch(
            "labro.cli.store_mod.get_prior_wip_run",
            return_value=(stale_wip_url, "Did stuff."),
        ),
        patch("labro.cli.pick", return_value=(task, agent_cfg)),
        # prepare_repo returns None for checked_out_wip — branch not found
        patch("labro.cli.prepare_repo", return_value=(repo_path, None)),
        patch("labro.cli.build_prompt", return_value="prompt text") as mock_build,
        patch("labro.cli.ClaudeCodeAgent") as MockAgent,
        patch("labro.cli.logger_mod.write_run"),
        patch("labro.cli.post_run_mod.post_run"),
    ):
        mock_instance = MockAgent.return_value
        mock_instance.invoke.return_value = agent_result

        _cmd_run_live(
            config_path=Path("labro.toml"),
            project_name="labro",
            db_path=db_path,
            repos_dir=repos_dir,
        )

    # build_prompt must get wip_branch=None (branch was cleared after checkout failed)
    build_kwargs = mock_build.call_args.kwargs
    assert build_kwargs.get("wip_branch") is None
    assert build_kwargs.get("prior_summary") is None

    conn.close()


def _make_task_with_push(project_name: str = "labro") -> Task:
    """Task with PUSH_DEFAULT permitted — required for WIP preservation on session limit."""
    return Task(
        task_id="test-task-id",
        source="gh-label",
        description="#1: Fix something\n\nBody text.",
        permitted_actions=[PermittedAction.COMMENT_ON_ISSUE, PermittedAction.PUSH_DEFAULT],
        repo="org/repo",
        item_type="issue",
        item_number=1,
        item_url="https://github.com/org/repo/issues/1",
        source_label="ai-dev",
        done_label="ai-dev-done",
        grafana_rule_uid=None,
    )


def test_session_limit_zero_tokens_skips_wip_preservation(tmp_path: Path) -> None:
    """session_limit_hit with output_tokens=0: preserve_wip must NOT be called."""
    db_path = tmp_path / "labro.db"
    repos_dir = tmp_path / "repos"
    conn = _open_mem_db()
    config = _make_config()
    task = _make_task_with_push()
    agent_cfg = _make_agent_cfg()
    # Simulate an immediate session-limit hit: no output tokens
    agent_result = AgentResult(
        outcome="failure",
        summary="You've hit your session limit · resets 9:40am (UTC)",
        failure_reason="session_limit_hit",
        output_tokens=0,
    )

    with (
        patch("labro.cli.load_config", return_value=config),
        patch("labro.cli.store_mod.open_db", return_value=conn),
        patch("labro.cli.store_mod.acquire_lock", return_value=True),
        patch("labro.cli.store_mod.release_lock"),
        patch("labro.cli.pick", return_value=(task, agent_cfg)),
        patch("labro.cli.prepare_repo", return_value=(tmp_path / "repos" / "org" / "repo", None)),
        patch("labro.cli.preserve_wip", return_value=None) as mock_preserve,
        patch("labro.cli.ClaudeCodeAgent") as MockAgent,
        patch("labro.cli.logger_mod.write_run"),
        patch("labro.cli.post_run_mod.post_run"),
    ):
        MockAgent.return_value.invoke.return_value = agent_result
        _cmd_run_live(
            config_path=Path("labro.toml"),
            project_name="labro",
            db_path=db_path,
            repos_dir=repos_dir,
        )

    mock_preserve.assert_not_called()
    conn.close()


def test_session_limit_with_output_tokens_and_push_perm_preserves_wip(tmp_path: Path) -> None:
    """session_limit_hit with output_tokens>0 and PUSH_DEFAULT: preserve_wip IS called."""
    db_path = tmp_path / "labro.db"
    repos_dir = tmp_path / "repos"
    repo_path = tmp_path / "repos" / "org" / "repo"
    conn = _open_mem_db()
    config = _make_config()
    task = _make_task_with_push()
    agent_cfg = _make_agent_cfg()
    agent_result = AgentResult(
        outcome="failure",
        summary="You've hit your session limit · resets 9:40am (UTC)",
        failure_reason="session_limit_hit",
        output_tokens=232,
    )

    with (
        patch("labro.cli.load_config", return_value=config),
        patch("labro.cli.store_mod.open_db", return_value=conn),
        patch("labro.cli.store_mod.acquire_lock", return_value=True),
        patch("labro.cli.store_mod.release_lock"),
        patch("labro.cli.pick", return_value=(task, agent_cfg)),
        patch("labro.cli.prepare_repo", return_value=(repo_path, None)),
        patch("labro.cli.preserve_wip", return_value=None) as mock_preserve,
        patch("labro.cli.ClaudeCodeAgent") as MockAgent,
        patch("labro.cli.logger_mod.write_run"),
        patch("labro.cli.post_run_mod.post_run"),
    ):
        MockAgent.return_value.invoke.return_value = agent_result
        _cmd_run_live(
            config_path=Path("labro.toml"),
            project_name="labro",
            db_path=db_path,
            repos_dir=repos_dir,
        )

    mock_preserve.assert_called_once()
    conn.close()


def test_session_limit_no_push_perm_skips_wip_preservation(tmp_path: Path) -> None:
    """session_limit_hit with output_tokens>0 but no PUSH_DEFAULT: preserve_wip is NOT called."""
    db_path = tmp_path / "labro.db"
    repos_dir = tmp_path / "repos"
    conn = _open_mem_db()
    config = _make_config()
    task = _make_task()  # no PUSH_DEFAULT
    agent_cfg = _make_agent_cfg()
    agent_result = AgentResult(
        outcome="failure",
        summary="You've hit your session limit · resets 9:40am (UTC)",
        failure_reason="session_limit_hit",
        output_tokens=100,
    )

    with (
        patch("labro.cli.load_config", return_value=config),
        patch("labro.cli.store_mod.open_db", return_value=conn),
        patch("labro.cli.store_mod.acquire_lock", return_value=True),
        patch("labro.cli.store_mod.release_lock"),
        patch("labro.cli.pick", return_value=(task, agent_cfg)),
        patch("labro.cli.prepare_repo", return_value=(tmp_path / "repos" / "org" / "repo", None)),
        patch("labro.cli.preserve_wip", return_value=None) as mock_preserve,
        patch("labro.cli.ClaudeCodeAgent") as MockAgent,
        patch("labro.cli.logger_mod.write_run"),
        patch("labro.cli.post_run_mod.post_run"),
    ):
        MockAgent.return_value.invoke.return_value = agent_result
        _cmd_run_live(
            config_path=Path("labro.toml"),
            project_name="labro",
            db_path=db_path,
            repos_dir=repos_dir,
        )

    mock_preserve.assert_not_called()
    conn.close()
