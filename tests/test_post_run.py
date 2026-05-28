"""Tests for src/labro/post_run.py — label transitions and failure comments.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from labro.models import AgentResult, Task
from labro.post_run import post_run

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_task(
    *,
    source: str = "gh-delegated",
    item_type: str | None = "issue",
    item_number: int | None = 42,
    source_label: str | None = "ai-dev",
    done_label: str | None = "ai-dev-done",
) -> Task:
    return Task(
        task_id="test-task-id",
        source=source,
        description="test task",
        permitted_actions=[],
        repo="owner/repo",
        item_type=item_type,
        item_number=item_number,
        item_url=None,
        source_label=source_label,
        done_label=done_label,
        grafana_rule_uid=None,
    )


def _make_result(*, outcome: str = "success", failure_reason: str | None = None) -> AgentResult:
    return AgentResult(
        outcome=outcome,
        summary="test summary",
        failure_reason=failure_reason,
        is_error=False,
        num_turns=1,
        total_cost_usd=0.01,
        duration_ms=500,
        input_tokens=10,
        output_tokens=5,
        cache_read_tokens=0,
        cache_write_tokens=0,
    )


def _edit_cmds(mock_run: MagicMock) -> list[list[str]]:
    """Return all subprocess calls that contain 'edit' (i.e. gh issue/pr edit calls)."""
    return [c[0][0] for c in mock_run.call_args_list if "edit" in c[0][0]]


def _comment_cmds(mock_run: MagicMock) -> list[list[str]]:
    """Return all subprocess calls that contain 'comment'."""
    return [c[0][0] for c in mock_run.call_args_list if "comment" in c[0][0]]


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------


@patch("labro.post_run._ensure_labels")
@patch("labro.post_run.subprocess.run")
def test_success_label_rule(mock_run: MagicMock, _mock_ensure: MagicMock) -> None:
    """label_rule path: done_label + ai-contributed added; source_label removed."""
    mock_run.return_value = MagicMock(returncode=0, stderr="")
    task = _make_task(source_label="ai-dev", done_label="ai-dev-done")
    post_run("run-1", task, _make_result(), outcome="success")

    edits = _edit_cmds(mock_run)
    assert len(edits) == 1
    cmd = edits[0]
    assert "--add-label" in cmd
    assert "ai-dev-done" in cmd
    assert "ai-contributed" in cmd
    assert "--remove-label" in cmd
    assert "ai-dev" in cmd
    assert _comment_cmds(mock_run) == []


@patch("labro.post_run._ensure_labels")
@patch("labro.post_run.subprocess.run")
def test_success_actor_rule_no_remove(mock_run: MagicMock, _mock_ensure: MagicMock) -> None:
    """actor_rule path (source_label=None): no --remove-label flag."""
    mock_run.return_value = MagicMock(returncode=0, stderr="")
    task = _make_task(source_label=None, done_label="ai-actor-done")
    post_run("run-2", task, _make_result(), outcome="success")

    edits = _edit_cmds(mock_run)
    assert len(edits) == 1
    cmd = edits[0]
    assert "--add-label" in cmd
    assert "ai-actor-done" in cmd
    assert "ai-contributed" in cmd
    assert "--remove-label" not in cmd


# ---------------------------------------------------------------------------
# Failure path
# ---------------------------------------------------------------------------


@patch("labro.post_run._ensure_labels")
@patch("labro.post_run.subprocess.run")
def test_failure_labels_and_comment(mock_run: MagicMock, _mock_ensure: MagicMock) -> None:
    """Failure: ai-failed + ai-contributed applied; comment posted with failure_reason."""
    mock_run.return_value = MagicMock(returncode=0, stderr="")
    task = _make_task()
    result = _make_result(outcome="failure", failure_reason="the agent timed out")
    post_run("run-3", task, result, outcome="failure")

    edits = _edit_cmds(mock_run)
    assert len(edits) == 1
    assert "ai-failed" in edits[0]
    assert "ai-contributed" in edits[0]

    comments = _comment_cmds(mock_run)
    assert len(comments) == 1
    assert "the agent timed out" in comments[0]


@patch("labro.post_run._ensure_labels")
@patch("labro.post_run.subprocess.run")
def test_failure_agent_result_none_generic_message(
    mock_run: MagicMock, _mock_ensure: MagicMock
) -> None:
    """Failure with agent_result=None (timeout): generic message posted."""
    mock_run.return_value = MagicMock(returncode=0, stderr="")
    task = _make_task()
    post_run("run-4", task, None, outcome="failure")

    comments = _comment_cmds(mock_run)
    assert len(comments) == 1
    body_idx = comments[0].index("--body") + 1
    assert "Labro" in comments[0][body_idx]


# ---------------------------------------------------------------------------
# Subprocess failure — must not raise
# ---------------------------------------------------------------------------


@patch("labro.post_run.subprocess.run")
def test_subprocess_failure_logs_warning_no_raise(
    mock_run: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    """A non-zero returncode from gh must log a warning and not raise."""
    mock_run.return_value = MagicMock(returncode=1, stderr="some gh error")
    task = _make_task()
    with caplog.at_level(logging.WARNING, logger="labro.post_run"):
        post_run("run-5", task, _make_result(), outcome="success")  # must not raise

    assert any("failed" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------------------
# Guard clauses
# ---------------------------------------------------------------------------


@patch("labro.post_run.subprocess.run")
def test_non_gh_delegated_source_no_subprocess(mock_run: MagicMock) -> None:
    """Non-gh-delegated tasks are silently skipped."""
    task = _make_task(source="grafana-alerts")
    post_run("run-6", task, _make_result(), outcome="success")
    mock_run.assert_not_called()


@patch("labro.post_run.subprocess.run")
def test_no_item_number_no_subprocess(mock_run: MagicMock) -> None:
    """Tasks without an item_number are silently skipped."""
    task = _make_task(item_number=None)
    post_run("run-7", task, _make_result(), outcome="success")
    mock_run.assert_not_called()
