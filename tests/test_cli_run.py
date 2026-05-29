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
        defaults=DefaultsConfig(model="claude-opus-4-7", max_turns=20, timeout_s=600),
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
        model="claude-opus-4-7",
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
        patch("labro.cli.prepare_repo", return_value=tmp_path / "repos" / "org" / "repo"),
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


def test_partial_outcome_stored_as_failure(tmp_path: Path) -> None:
    """AgentResult.outcome='partial' is stored as outcome='failure' (ARCHITECTURE line 263)."""
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
        patch("labro.cli.prepare_repo", return_value=tmp_path / "repos" / "org" / "repo"),
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
    assert call_kwargs["outcome"] == "failure"

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
        patch("labro.cli.prepare_repo", return_value=tmp_path / "repos" / "org" / "repo"),
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
        patch("labro.cli.prepare_repo", return_value=tmp_path / "repos" / "org" / "repo"),
        patch("labro.cli.ClaudeCodeAgent") as MockAgent,
        patch("labro.cli.logger_mod.write_run"),
        patch("labro.cli.assignee_mod.assign_claude") as mock_assign,
        patch("labro.cli.assignee_mod.restore_assignees") as mock_restore,
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
        patch("labro.cli.prepare_repo", return_value=tmp_path / "repos" / "org" / "repo"),
        patch("labro.cli.ClaudeCodeAgent") as MockAgent,
        patch("labro.cli.logger_mod.write_run"),
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
