"""Tests for src/labro/logger.py — run record persistence.

All tests use SQLite :memory: databases.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from labro.logger import write_run
from labro.models import AgentConfig, AgentResult, Task, make_task_id
from labro.store import open_db

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _memory_db() -> sqlite3.Connection:
    return open_db(":memory:")


def _make_task(**kwargs: Any) -> Task:
    defaults: dict[str, Any] = dict(
        task_id=make_task_id(),
        source="gh-label",
        description="Fix the flaky test",
        permitted_actions=[],
        repo="owner/repo",
        item_type="issue",
        item_number=42,
        item_url="https://github.com/owner/repo/issues/42",
        source_label="ai-dev",
        done_label="ai-done",
        grafana_rule_uid=None,
    )
    defaults.update(kwargs)
    return Task(**defaults)


def _make_agent_cfg(**kwargs: Any) -> AgentConfig:
    defaults: dict[str, Any] = dict(
        agent="claude-code",
        model="claude-sonnet-4-6",
        max_turns=10,
        timeout_s=300,
    )
    defaults.update(kwargs)
    return AgentConfig(**defaults)


def _make_agent_result(**kwargs: Any) -> AgentResult:
    defaults: dict[str, Any] = dict(
        outcome="success",
        summary="Closed the flaky test issue.",
        actions_taken=["commented on issue #42", "closed issue #42"],
        items_created=[],
        failure_reason=None,
        is_error=False,
        num_turns=3,
        total_cost_usd=0.0123,
        duration_ms=4500,
        input_tokens=1000,
        output_tokens=200,
        cache_read_tokens=50,
        cache_write_tokens=10,
    )
    defaults.update(kwargs)
    return AgentResult(**defaults)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_write_run_success() -> None:
    """A success run is persisted with all fields set correctly."""
    conn = _memory_db()
    task = _make_task()
    agent_cfg = _make_agent_cfg()
    agent_result = _make_agent_result()

    write_run(
        conn,
        run_id="run-001",
        project="myproject",
        task=task,
        agent_cfg=agent_cfg,
        agent_result=agent_result,
        outcome="success",
        failure_reason=None,
        started_at="2026-05-27T10:00:00Z",
        ended_at="2026-05-27T10:00:04Z",
    )

    row = conn.execute("SELECT * FROM runs WHERE run_id = 'run-001'").fetchone()
    assert row is not None
    assert row["run_id"] == "run-001"
    assert row["project"] == "myproject"
    assert row["task_source"] == "gh-label"
    assert row["task_description"] == "Fix the flaky test"
    assert row["item_url"] == "https://github.com/owner/repo/issues/42"
    assert row["trigger_label"] == "ai-dev"
    assert row["agent"] == "claude-code"
    assert row["model"] == "claude-sonnet-4-6"
    assert row["started_at"] == "2026-05-27T10:00:00Z"
    assert row["ended_at"] == "2026-05-27T10:00:04Z"
    assert row["outcome"] == "success"
    assert row["turns_used"] == 3
    assert abs(row["total_cost_usd"] - 0.0123) < 1e-9
    assert row["input_tokens"] == 1000
    assert row["output_tokens"] == 200
    assert row["cache_read_tokens"] == 50
    assert row["cache_write_tokens"] == 10
    assert row["summary"] == "Closed the flaky test issue."
    assert row["failure_reason"] is None
    assert abs(row["duration_s"] - 4.5) < 1e-9


def test_write_run_trigger_label_null_for_actor_rule() -> None:
    """trigger_label is NULL when the task has no source_label (actor_rule trigger)."""
    conn = _memory_db()
    task = _make_task(source_label=None)

    write_run(
        conn,
        run_id="run-actor",
        project="myproject",
        task=task,
        agent_cfg=_make_agent_cfg(),
        agent_result=_make_agent_result(),
        outcome="success",
        failure_reason=None,
        started_at="2026-05-27T10:00:00Z",
        ended_at="2026-05-27T10:00:04Z",
    )

    row = conn.execute("SELECT trigger_label FROM runs WHERE run_id = 'run-actor'").fetchone()
    assert row["trigger_label"] is None


def test_write_run_skipped_no_task() -> None:
    """A skipped run with no task or agent result stores NULLs for optional columns."""
    conn = _memory_db()

    write_run(
        conn,
        run_id="run-skip",
        project="myproject",
        task=None,
        agent_cfg=None,
        agent_result=None,
        outcome="skipped",
        failure_reason="skipped: no task found",
        started_at="2026-05-27T10:00:00Z",
        ended_at="2026-05-27T10:00:00Z",
    )

    row = conn.execute("SELECT * FROM runs WHERE run_id = 'run-skip'").fetchone()
    assert row is not None
    assert row["outcome"] == "skipped"
    assert row["task_source"] is None
    assert row["task_description"] is None
    assert row["item_url"] is None
    assert row["trigger_label"] is None
    assert row["agent"] is None
    assert row["model"] is None
    assert row["turns_used"] is None
    assert row["total_cost_usd"] is None
    assert row["summary"] is None
    assert row["actions_taken"] is None
    assert row["failure_reason"] == "skipped: no task found"
    assert row["duration_s"] is None


def test_write_run_failure() -> None:
    """A failure run stores the failure_reason and outcome='failure'."""
    conn = _memory_db()
    task = _make_task()
    agent_cfg = _make_agent_cfg()
    agent_result = _make_agent_result(
        outcome="failure",
        summary="Agent could not access the repo.",
        failure_reason="subprocess timeout after 300s",
    )

    write_run(
        conn,
        run_id="run-fail",
        project="myproject",
        task=task,
        agent_cfg=agent_cfg,
        agent_result=agent_result,
        outcome="failure",
        failure_reason="subprocess timeout after 300s",
        started_at="2026-05-27T10:00:00Z",
        ended_at="2026-05-27T10:05:00Z",
    )

    row = conn.execute("SELECT * FROM runs WHERE run_id = 'run-fail'").fetchone()
    assert row["outcome"] == "failure"
    assert row["failure_reason"] == "subprocess timeout after 300s"


def test_actions_taken_serialised_as_json() -> None:
    """The actions_taken column must be a parseable JSON array of strings."""
    conn = _memory_db()
    agent_result = _make_agent_result(actions_taken=["commented on #1", "opened PR #2"])

    write_run(
        conn,
        run_id="run-actions",
        project="myproject",
        task=_make_task(),
        agent_cfg=_make_agent_cfg(),
        agent_result=agent_result,
        outcome="success",
        failure_reason=None,
        started_at="2026-05-27T10:00:00Z",
        ended_at="2026-05-27T10:00:05Z",
    )

    row = conn.execute("SELECT actions_taken FROM runs WHERE run_id = 'run-actions'").fetchone()
    parsed = json.loads(row["actions_taken"])
    assert isinstance(parsed, list)
    assert parsed == ["commented on #1", "opened PR #2"]
    assert all(isinstance(item, str) for item in parsed)


def test_write_run_empty_actions_taken() -> None:
    """An empty actions_taken list is serialised as '[]'."""
    conn = _memory_db()
    agent_result = _make_agent_result(actions_taken=[])

    write_run(
        conn,
        run_id="run-empty",
        project="myproject",
        task=_make_task(),
        agent_cfg=_make_agent_cfg(),
        agent_result=agent_result,
        outcome="success",
        failure_reason=None,
        started_at="2026-05-27T10:00:00Z",
        ended_at="2026-05-27T10:00:01Z",
    )

    row = conn.execute("SELECT actions_taken FROM runs WHERE run_id = 'run-empty'").fetchone()
    assert json.loads(row["actions_taken"]) == []


def test_write_run_stores_wip_branch_url() -> None:
    """wip_branch_url is persisted when supplied."""
    conn = _memory_db()
    wip_url = "https://github.com/owner/repo/tree/labro-wip/run-wip"

    write_run(
        conn,
        run_id="run-wip",
        project="myproject",
        task=_make_task(),
        agent_cfg=_make_agent_cfg(),
        agent_result=_make_agent_result(outcome="partial"),
        outcome="partial",
        failure_reason="error_max_turns",
        started_at="2026-05-27T10:00:00Z",
        ended_at="2026-05-27T10:05:00Z",
        wip_branch_url=wip_url,
    )

    row = conn.execute("SELECT wip_branch_url FROM runs WHERE run_id = 'run-wip'").fetchone()
    assert row["wip_branch_url"] == wip_url


def test_write_run_wip_branch_url_defaults_to_null() -> None:
    """wip_branch_url is NULL when not supplied (success / failure paths)."""
    conn = _memory_db()

    write_run(
        conn,
        run_id="run-no-wip",
        project="myproject",
        task=_make_task(),
        agent_cfg=_make_agent_cfg(),
        agent_result=_make_agent_result(),
        outcome="success",
        failure_reason=None,
        started_at="2026-05-27T10:00:00Z",
        ended_at="2026-05-27T10:00:05Z",
    )

    row = conn.execute("SELECT wip_branch_url FROM runs WHERE run_id = 'run-no-wip'").fetchone()
    assert row["wip_branch_url"] is None
