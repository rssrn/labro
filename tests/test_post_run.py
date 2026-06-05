"""Tests for src/labro/post_run.py — label transitions and failure comments.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from labro.models import AgentConfig, AgentResult, Task
from labro.post_run import post_run, pre_run

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_task(
    *,
    source: str = "gh-label",
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
    """Return all gh-api subprocess calls that hit the labels REST endpoint."""
    return [
        c[0][0]
        for c in mock_run.call_args_list
        if c[0][0][:2] == ["gh", "api"] and any("/labels" in a for a in c[0][0])
    ]


def _comment_cmds(mock_run: MagicMock) -> list[list[str]]:
    """Return all subprocess calls that contain 'comment'."""
    return [c[0][0] for c in mock_run.call_args_list if "comment" in c[0][0]]


# ---------------------------------------------------------------------------
# pre_run
# ---------------------------------------------------------------------------


def _make_agent_cfg(slug: str = "claude-code:anthropic/claude-sonnet-4-6") -> AgentConfig:
    return AgentConfig.from_slug(slug, max_turns=10, timeout_s=300)


@patch("labro.post_run.subprocess.run")
def test_pre_run_comment_includes_label_and_slug(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=0, stderr="")
    task = _make_task(source_label="ai-dev")
    pre_run(task, _make_agent_cfg())
    cmds = _comment_cmds(mock_run)
    assert len(cmds) == 1
    body = cmds[0][cmds[0].index("--body") + 1]
    assert "ai-dev" in body
    assert "claude-code:anthropic/claude-sonnet-4-6" in body


@patch("labro.post_run.subprocess.run")
def test_pre_run_comment_no_source_label(mock_run: MagicMock) -> None:
    mock_run.return_value = MagicMock(returncode=0, stderr="")
    task = _make_task(source_label=None)
    pre_run(task, _make_agent_cfg())
    cmds = _comment_cmds(mock_run)
    assert len(cmds) == 1
    body = cmds[0][cmds[0].index("--body") + 1]
    assert "claude-code:anthropic/claude-sonnet-4-6" in body


@patch("labro.post_run.subprocess.run")
def test_pre_run_noop_when_no_item_number(mock_run: MagicMock) -> None:
    task = _make_task(item_number=None)
    pre_run(task, _make_agent_cfg())
    mock_run.assert_not_called()


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
    # one POST (add) + one DELETE (remove)
    assert len(edits) == 2
    add_cmd = edits[0]
    assert "POST" in add_cmd
    assert "labels[]=ai-dev-done" in add_cmd
    assert "labels[]=ai-contributed" in add_cmd
    del_cmd = edits[1]
    assert "DELETE" in del_cmd
    assert del_cmd[-1].endswith("/labels/ai-dev")
    assert _comment_cmds(mock_run) == []


@patch("labro.post_run._ensure_labels")
@patch("labro.post_run.subprocess.run")
def test_success_gh_author_no_remove(mock_run: MagicMock, _mock_ensure: MagicMock) -> None:
    """gh-author path (source_label=None): done_label applied, no label removal."""
    mock_run.return_value = MagicMock(returncode=0, stderr="")
    task = _make_task(source="gh-author", source_label=None, done_label="ai-actor-done")
    post_run("run-2", task, _make_result(), outcome="success")

    edits = _edit_cmds(mock_run)
    assert len(edits) == 1
    cmd = edits[0]
    assert "POST" in cmd
    assert "labels[]=ai-actor-done" in cmd
    assert "labels[]=ai-contributed" in cmd
    assert all("DELETE" not in c for c in edits)


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
    assert "labels[]=ai-failed" in edits[0]
    assert "labels[]=ai-contributed" in edits[0]

    comments = _comment_cmds(mock_run)
    assert len(comments) == 1
    body = comments[0][comments[0].index("--body") + 1]
    assert "Labro's agent" in body
    assert "was assigned this issue" in body
    assert "the agent timed out" in body


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
def test_non_gh_label_source_no_subprocess(mock_run: MagicMock) -> None:
    """Non-gh-label tasks are silently skipped."""
    task = _make_task(source="grafana-alerts")
    post_run("run-6", task, _make_result(), outcome="success")
    mock_run.assert_not_called()


@patch("labro.post_run.subprocess.run")
def test_no_item_number_no_subprocess(mock_run: MagicMock) -> None:
    """Tasks without an item_number are silently skipped."""
    task = _make_task(item_number=None)
    post_run("run-7", task, _make_result(), outcome="success")
    mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# Partial / handover path
# ---------------------------------------------------------------------------


@patch("labro.post_run._ensure_labels")
@patch("labro.post_run.subprocess.run")
def test_partial_adds_handover_labels(mock_run: MagicMock, _mock_ensure: MagicMock) -> None:
    """Partial outcome: ai-handover + ai-contributed applied."""
    mock_run.return_value = MagicMock(returncode=0, stderr="")
    task = _make_task()
    result = _make_result(outcome="partial")
    post_run("run-p1", task, result, outcome="partial")

    edits = _edit_cmds(mock_run)
    assert len(edits) == 1
    assert "labels[]=ai-handover" in edits[0]
    assert "labels[]=ai-contributed" in edits[0]


@patch("labro.post_run._ensure_labels")
@patch("labro.post_run.subprocess.run")
def test_partial_posts_handover_comment_with_wip_url(
    mock_run: MagicMock, _mock_ensure: MagicMock
) -> None:
    """Partial outcome: handover comment includes WIP branch URL and re-trigger instruction."""
    mock_run.return_value = MagicMock(returncode=0, stderr="")
    task = _make_task()
    result = _make_result(outcome="partial")
    wip_url = "https://github.com/owner/repo/tree/labro-wip/run-abc"
    post_run("run-p2", task, result, outcome="partial", wip_branch_url=wip_url)

    comments = _comment_cmds(mock_run)
    assert len(comments) == 1
    body = comments[0][comments[0].index("--body") + 1]
    assert "ran out of turns" in body
    assert wip_url in body
    assert "ai-handover" in body
    assert "re-queue" in body


@patch("labro.post_run._ensure_labels")
@patch("labro.post_run.subprocess.run")
def test_partial_posts_handover_comment_without_wip(
    mock_run: MagicMock, _mock_ensure: MagicMock
) -> None:
    """Partial outcome without a WIP branch: no branch link, but re-trigger instruction present."""
    mock_run.return_value = MagicMock(returncode=0, stderr="")
    task = _make_task()
    result = _make_result(outcome="partial")
    post_run("run-p3", task, result, outcome="partial", wip_branch_url=None)

    comments = _comment_cmds(mock_run)
    assert len(comments) == 1
    body = comments[0][comments[0].index("--body") + 1]
    assert "ran out of turns" in body
    assert "github.com" not in body
    assert "ai-handover" in body


@patch("labro.post_run._ensure_labels")
@patch("labro.post_run.subprocess.run")
def test_failure_with_wip_url_appends_branch_link(
    mock_run: MagicMock, _mock_ensure: MagicMock
) -> None:
    """Failure with a WIP branch URL: branch link appended to the failure comment."""
    mock_run.return_value = MagicMock(returncode=0, stderr="")
    task = _make_task()
    result = _make_result(outcome="failure", failure_reason="unexpected crash")
    wip_url = "https://github.com/owner/repo/tree/labro-wip/run-xyz"
    post_run("run-f1", task, result, outcome="failure", wip_branch_url=wip_url)

    comments = _comment_cmds(mock_run)
    assert len(comments) == 1
    body = comments[0][comments[0].index("--body") + 1]
    assert wip_url in body


@patch("labro.post_run._ensure_labels")
@patch("labro.post_run.subprocess.run")
def test_session_limit_no_output_skips_labels_posts_comment(
    mock_run: MagicMock, _mock_ensure: MagicMock
) -> None:
    """session_limit_hit with no WIP: no ai-failed label, comment posted, issue stays pickable."""
    mock_run.return_value = MagicMock(returncode=0, stderr="")
    task = _make_task()
    result = _make_result(outcome="failure", failure_reason="session_limit_hit")
    post_run("run-sl1", task, result, outcome="failure")

    # No label edit — issue must remain pickable
    edits = _edit_cmds(mock_run)
    assert not any("ai-failed" in " ".join(cmd) for cmd in edits)
    assert not any("ai-contributed" in " ".join(cmd) for cmd in edits)

    # A comment is posted explaining the situation
    comments = _comment_cmds(mock_run)
    assert len(comments) == 1
    body = comments[0][comments[0].index("--body") + 1]
    assert "session limit" in body.lower()
    assert "remains eligible to be picked in future runs" in body
    assert "re-queued automatically" not in body


@patch("labro.post_run._ensure_labels")
@patch("labro.post_run.subprocess.run")
def test_session_limit_with_wip_applies_handover_labels(
    mock_run: MagicMock, _mock_ensure: MagicMock
) -> None:
    """session_limit_hit with a WIP branch: ai-handover label applied, handover comment posted."""
    mock_run.return_value = MagicMock(returncode=0, stderr="")
    task = _make_task()
    result = _make_result(outcome="failure", failure_reason="session_limit_hit")
    wip_url = "https://github.com/owner/repo/tree/labro-wip/run-sl2"
    post_run("run-sl2", task, result, outcome="failure", wip_branch_url=wip_url)

    edits = _edit_cmds(mock_run)
    assert any("ai-handover" in " ".join(cmd) for cmd in edits)
    assert not any("ai-failed" in " ".join(cmd) for cmd in edits)

    comments = _comment_cmds(mock_run)
    assert len(comments) == 1
    body = comments[0][comments[0].index("--body") + 1]
    assert wip_url in body
    assert "session limit" in body.lower()
    assert "ai-handover" in body


@patch("labro.post_run._ensure_labels")
@patch("labro.post_run.subprocess.run")
def test_partial_fresh_run_uses_new_branch_wording(
    mock_run: MagicMock, _mock_ensure: MagicMock
) -> None:
    """Partial outcome on first run: comment says 'new branch'."""
    mock_run.return_value = MagicMock(returncode=0, stderr="")
    task = _make_task()
    result = _make_result(outcome="partial")
    wip_url = "https://github.com/owner/repo/tree/labro-wip/run-new"
    post_run("run-p4", task, result, outcome="partial", wip_branch_url=wip_url, resuming_wip=False)

    comments = _comment_cmds(mock_run)
    body = comments[0][comments[0].index("--body") + 1]
    assert "new branch" in body
    assert wip_url in body


@patch("labro.post_run._ensure_labels")
@patch("labro.post_run.subprocess.run")
def test_partial_resume_run_uses_existing_branch_wording(
    mock_run: MagicMock, _mock_ensure: MagicMock
) -> None:
    """Partial outcome on a resume run: comment says 'Existing WIP branch updated'."""
    mock_run.return_value = MagicMock(returncode=0, stderr="")
    task = _make_task()
    result = _make_result(outcome="partial")
    wip_url = "https://github.com/owner/repo/tree/labro-wip/prior-run"
    post_run("run-p5", task, result, outcome="partial", wip_branch_url=wip_url, resuming_wip=True)

    comments = _comment_cmds(mock_run)
    body = comments[0][comments[0].index("--body") + 1]
    assert "Existing WIP branch updated" in body
    assert wip_url in body
