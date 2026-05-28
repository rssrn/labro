"""Tests for src/labro/store.py — SQLite schema, lock management, and budget query.

All tests use SQLite :memory: databases; no temp files required.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import sqlite3

import pytest

from labro.store import acquire_lock, get_daily_spend, insert_items_touched, open_db, release_lock

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _memory_db() -> sqlite3.Connection:
    """Return a fresh in-memory database with the full schema applied."""
    return open_db(":memory:")


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row["name"] for row in rows}


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_open_db_creates_tables() -> None:
    conn = _memory_db()
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    assert {"runs", "project_locks", "items_touched"}.issubset(tables)


def test_runs_table_has_expected_columns() -> None:
    conn = _memory_db()
    cols = _table_columns(conn, "runs")
    expected = {
        "run_id",
        "project",
        "task_source",
        "task_description",
        "item_url",
        "agent",
        "model",
        "started_at",
        "ended_at",
        "duration_s",
        "outcome",
        "turns_used",
        "total_cost_usd",
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "summary",
        "actions_taken",
        "failure_reason",
    }
    assert expected == cols


def test_project_locks_table_has_expected_columns() -> None:
    conn = _memory_db()
    cols = _table_columns(conn, "project_locks")
    assert cols == {"project", "locked_at"}


def test_items_touched_table_has_expected_columns() -> None:
    conn = _memory_db()
    cols = _table_columns(conn, "items_touched")
    expected = {
        "id",
        "run_id",
        "repo",
        "item_type",
        "item_number",
        "outcome_state",
        "follow_up_commits",
        "thumbs_up",
        "thumbs_down",
        "signals_collected_at",
    }
    assert expected == cols


# ---------------------------------------------------------------------------
# acquire_lock / release_lock
# ---------------------------------------------------------------------------


def test_acquire_lock_success() -> None:
    conn = _memory_db()
    result = acquire_lock(conn, "myproject", timeout_s=300)
    assert result is True
    row = conn.execute("SELECT project FROM project_locks WHERE project = 'myproject'").fetchone()
    assert row is not None


def test_acquire_lock_contention_non_stale() -> None:
    conn = _memory_db()
    acquire_lock(conn, "myproject", timeout_s=300)
    # Second acquire for same project — lock is fresh → should fail
    result = acquire_lock(conn, "myproject", timeout_s=300)
    assert result is False
    # Still exactly one lock row
    count = conn.execute(
        "SELECT COUNT(*) FROM project_locks WHERE project = 'myproject'"
    ).fetchone()[0]
    assert count == 1


def test_acquire_lock_stale_overwritten() -> None:
    """A lock older than timeout_s + 60s must be overwritten and True returned."""
    conn = _memory_db()
    # Insert a lock timestamped far in the past (2 hours ago).
    conn.execute(
        "INSERT INTO project_locks (project, locked_at)"
        " VALUES ('myproject', datetime('now', '-2 hours'))"
    )
    conn.commit()

    result = acquire_lock(conn, "myproject", timeout_s=300)
    assert result is True
    # Row must have been replaced — locked_at must now be recent (within 5s).
    row = conn.execute(
        """
        SELECT (strftime('%s', 'now') - strftime('%s', locked_at)) AS age_s
        FROM project_locks WHERE project = 'myproject'
        """
    ).fetchone()
    assert row["age_s"] < 5


def test_acquire_lock_within_grace_period() -> None:
    """A lock at exactly timeout_s + 59s (just inside the grace window) is non-stale → False."""
    conn = _memory_db()
    # timeout_s=300 → stale threshold = 360s. Insert a lock that is 359s old.
    conn.execute(
        "INSERT INTO project_locks (project, locked_at)"
        " VALUES ('myproject', datetime('now', '-359 seconds'))"
    )
    conn.commit()

    result = acquire_lock(conn, "myproject", timeout_s=300)
    assert result is False


def test_release_lock() -> None:
    conn = _memory_db()
    acquire_lock(conn, "myproject", timeout_s=300)
    release_lock(conn, "myproject")
    row = conn.execute("SELECT project FROM project_locks WHERE project = 'myproject'").fetchone()
    assert row is None


def test_release_lock_idempotent() -> None:
    """Releasing a lock that was never acquired should not raise."""
    conn = _memory_db()
    release_lock(conn, "nonexistent")  # must not raise


# ---------------------------------------------------------------------------
# get_daily_spend
# ---------------------------------------------------------------------------


def test_get_daily_spend_empty() -> None:
    conn = _memory_db()
    spend = get_daily_spend(conn, "myproject")
    assert spend == 0.0


def test_get_daily_spend_today_only() -> None:
    """Only today's run costs are included; yesterday's rows are excluded."""
    conn = _memory_db()

    # Insert one run today and one yesterday for the same project.
    # Use parameterised strftime so each date is computed inside SQLite.
    _sql = (
        "INSERT INTO runs (run_id, project, started_at, outcome, total_cost_usd)"
        " VALUES (?, 'myproject',"
        " strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ?), 'success', ?)"
    )
    conn.execute(_sql, ("run-today", "0 days", 0.05))
    conn.execute(_sql, ("run-yesterday", "-1 day", 0.10))
    conn.commit()

    spend = get_daily_spend(conn, "myproject")
    assert abs(spend - 0.05) < 1e-9


# ---------------------------------------------------------------------------
# insert_items_touched
# ---------------------------------------------------------------------------


def test_insert_items_touched_basic() -> None:
    """insert_items_touched writes a row and it can be retrieved."""
    conn = _memory_db()
    # items_touched has a FK to runs, but SQLite doesn't enforce FKs by default.
    insert_items_touched(conn, "run-abc", "owner/repo", "issue", 7)
    row = conn.execute(
        "SELECT run_id, repo, item_type, item_number FROM items_touched WHERE run_id = 'run-abc'"
    ).fetchone()
    assert row is not None
    assert row["run_id"] == "run-abc"
    assert row["repo"] == "owner/repo"
    assert row["item_type"] == "issue"
    assert row["item_number"] == 7


def test_insert_items_touched_pr() -> None:
    conn = _memory_db()
    insert_items_touched(conn, "run-pr", "owner/repo", "pr", 99)
    row = conn.execute("SELECT item_type FROM items_touched WHERE run_id = 'run-pr'").fetchone()
    assert row["item_type"] == "pr"


def test_insert_items_touched_invalid_item_type_raises() -> None:
    """The CHECK constraint rejects unknown item_type values."""
    import sqlite3 as _sqlite3

    conn = _memory_db()
    conn.execute("PRAGMA foreign_keys = ON")
    with pytest.raises(_sqlite3.IntegrityError):
        insert_items_touched(conn, "run-bad", "owner/repo", "comment", 1)


def test_get_daily_spend_different_project_excluded() -> None:
    conn = _memory_db()
    _sql = (
        "INSERT INTO runs (run_id, project, started_at, outcome, total_cost_usd)"
        " VALUES ('run-other', 'other-project',"
        " strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), 'success', 0.99)"
    )
    conn.execute(_sql)
    conn.commit()

    spend = get_daily_spend(conn, "myproject")
    assert spend == 0.0
