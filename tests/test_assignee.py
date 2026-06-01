"""Tests for labro.assignee — assign_claude and restore_assignees.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from labro.assignee import assign_claude, comment_assignment, restore_assignees
from labro.config.schema import PermittedAction
from labro.models import Task


def _make_task(
    item_type: str = "issue",
    item_number: int = 42,
    assignees: list[str] | None = None,
) -> Task:
    return Task(
        task_id="test-task-id",
        source="gh-label",
        description="#42: Some task",
        permitted_actions=[PermittedAction.COMMENT_ON_ISSUE],
        repo="org/repo",
        item_type=item_type,
        item_number=item_number,
        item_url="https://github.com/org/repo/issues/42",
        source_label="ai-dev",
        done_label="ai-dev-done",
        grafana_rule_uid=None,
        assignees=assignees or [],
    )


def _no_item_task() -> Task:
    return Task(
        task_id="test-task-id",
        source="grafana-alerts",
        description="Some alert",
        permitted_actions=[],
        repo="org/repo",
        item_type=None,
        item_number=None,
        item_url=None,
        source_label=None,
        done_label=None,
        grafana_rule_uid="rule-uid-123",
    )


# ── assign_claude ──────────────────────────────────────────────────────────────


def test_assign_claude_calls_gh_add_assignee() -> None:
    task = _make_task()
    with patch("labro.assignee.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        assign_claude(task, "claude-code-bot")
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert cmd[:4] == ["gh", "issue", "edit", "42"]
    assert "--repo" in cmd
    assert "org/repo" in cmd
    assert "--add-assignee" in cmd
    assert "claude-code-bot" in cmd
    assert "--remove-assignee" not in cmd


def test_assign_claude_uses_pr_subcommand_for_pr_item() -> None:
    task = _make_task(item_type="pr", item_number=7)
    with patch("labro.assignee.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        assign_claude(task, "claude-code-bot")
    cmd = mock_run.call_args[0][0]
    assert cmd[1] == "pr"


def test_assign_claude_noop_when_no_item() -> None:
    task = _no_item_task()
    with patch("labro.assignee.subprocess.run") as mock_run:
        assign_claude(task, "claude-code-bot")
    mock_run.assert_not_called()


def test_assign_claude_dry_run_does_not_call_gh() -> None:
    task = _make_task()
    with patch("labro.assignee.subprocess.run") as mock_run:
        assign_claude(task, "claude-code-bot", dry_run=True)
    mock_run.assert_not_called()


def test_assign_claude_soft_fail_on_gh_error(caplog: pytest.LogCaptureFixture) -> None:
    task = _make_task()
    with patch("labro.assignee.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr="422 Unprocessable Entity")
        assign_claude(task, "claude-code-bot")  # must not raise
    assert any("failed" in r.message.lower() for r in caplog.records)


# ── comment_assignment ────────────────────────────────────────────────────────


def test_comment_assignment_posts_expected_body() -> None:
    task = _make_task()
    with patch("labro.assignee.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        comment_assignment(task, "claude-code-bot")
    mock_run.assert_called_once_with(
        [
            "gh",
            "issue",
            "comment",
            "42",
            "--repo",
            "org/repo",
            "--body",
            "Labro assigning issue to claude-code-bot for action.",
        ],
        capture_output=True,
        text=True,
    )


def test_comment_assignment_noop_when_no_item() -> None:
    task = _no_item_task()
    with patch("labro.assignee.subprocess.run") as mock_run:
        comment_assignment(task, "claude-code-bot")
    mock_run.assert_not_called()


def test_comment_assignment_dry_run_does_not_call_gh() -> None:
    task = _make_task()
    with patch("labro.assignee.subprocess.run") as mock_run:
        comment_assignment(task, "claude-code-bot", dry_run=True)
    mock_run.assert_not_called()


def test_comment_assignment_soft_fail_on_gh_error(caplog: pytest.LogCaptureFixture) -> None:
    task = _make_task()
    with patch("labro.assignee.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr="not found")
        comment_assignment(task, "claude-code-bot")  # must not raise
    assert any("gh issue comment failed" in r.message for r in caplog.records)


# ── restore_assignees ──────────────────────────────────────────────────────────


def test_restore_assignees_removes_claude_and_adds_original() -> None:
    task = _make_task(assignees=["alice"])
    with patch("labro.assignee.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        restore_assignees(task, "claude-code-bot")
    cmd = mock_run.call_args[0][0]
    assert "--remove-assignee" in cmd
    assert "claude-code-bot" in cmd
    assert "--add-assignee" in cmd
    assert "alice" in cmd


def test_restore_assignees_removes_claude_when_no_original() -> None:
    task = _make_task(assignees=[])
    with patch("labro.assignee.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        restore_assignees(task, "claude-code-bot")
    cmd = mock_run.call_args[0][0]
    assert "--remove-assignee" in cmd
    assert "claude-code-bot" in cmd
    assert "--add-assignee" not in cmd


def test_restore_assignees_noop_when_no_item() -> None:
    task = _no_item_task()
    with patch("labro.assignee.subprocess.run") as mock_run:
        restore_assignees(task, "claude-code-bot")
    mock_run.assert_not_called()


def test_restore_assignees_dry_run_does_not_call_gh() -> None:
    task = _make_task(assignees=["alice"])
    with patch("labro.assignee.subprocess.run") as mock_run:
        restore_assignees(task, "claude-code-bot", dry_run=True)
    mock_run.assert_not_called()


def test_restore_assignees_soft_fail_on_gh_error(caplog: pytest.LogCaptureFixture) -> None:
    task = _make_task(assignees=["alice"])
    with patch("labro.assignee.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr="503 Service Unavailable")
        restore_assignees(task, "claude-code-bot")  # must not raise
    assert any("failed" in r.message.lower() for r in caplog.records)


def test_restore_assignees_multiple_original_assignees() -> None:
    task = _make_task(assignees=["alice", "bob"])
    with patch("labro.assignee.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        restore_assignees(task, "claude-code-bot")
    cmd = mock_run.call_args[0][0]
    # Both original assignees should be re-added
    add_indices = [i for i, x in enumerate(cmd) if x == "--add-assignee"]
    added = [cmd[i + 1] for i in add_indices]
    assert set(added) == {"alice", "bob"}
