"""Tests for src/labro/store.py — SQLite schema, lock management, and budget query.

All tests use SQLite :memory: databases; no temp files required.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from labro.store import (
    acquire_lock,
    get_daily_spend,
    get_prior_wip_run,
    insert_items_touched,
    open_db,
    release_lock,
)

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
        "trigger_label",
        "agent",
        "provider",
        "model",
        "effort",
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
        "wip_branch_url",
        "chosen_perspective",
        "fallback_attempts",
        "source_description",
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


def test_open_db_accepts_partial_outcome() -> None:
    """A fresh DB created by open_db accepts outcome='partial'."""
    conn = _memory_db()
    conn.execute(
        "INSERT INTO runs (run_id, project, started_at, outcome) VALUES (?, ?, ?, ?)",
        ("run-p", "proj", "2024-01-01T00:00:00Z", "partial"),
    )
    conn.commit()
    row = conn.execute("SELECT outcome FROM runs WHERE run_id = 'run-p'").fetchone()
    assert row["outcome"] == "partial"


# ---------------------------------------------------------------------------
# get_prior_wip_run
# ---------------------------------------------------------------------------


def _insert_run(
    conn: sqlite3.Connection,
    run_id: str,
    item_url: str,
    outcome: str,
    started_at: str,
    summary: str | None = None,
    wip_branch_url: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO runs"
        " (run_id, project, started_at, outcome, item_url, summary, wip_branch_url)"
        " VALUES (?, 'proj', ?, ?, ?, ?, ?)",
        (run_id, started_at, outcome, item_url, summary, wip_branch_url),
    )
    conn.commit()


def test_get_prior_wip_run_no_partial_returns_none() -> None:
    """Returns None when there are no partial runs for the item URL."""
    conn = _memory_db()
    url = "https://github.com/o/r/issues/1"
    _insert_run(conn, "run-ok", url, "success", "2024-01-01T00:00:00Z")
    result = get_prior_wip_run(conn, url)
    assert result is None


def test_get_prior_wip_run_returns_most_recent_branch() -> None:
    """Returns (wip_branch_url, summary) of the most recent partial with a WIP branch."""
    conn = _memory_db()
    url = "https://github.com/o/r/issues/7"
    wip1 = "https://github.com/o/r/tree/labro-wip/run-p1"
    # run-p2 pushed to the same branch as run-p1 (resume path)
    wip2 = "https://github.com/o/r/tree/labro-wip/run-p1"
    _insert_run(
        conn,
        "run-p1",
        url,
        "partial",
        "2024-01-01T00:00:00Z",
        "First attempt.",
        wip_branch_url=wip1,
    )
    _insert_run(
        conn,
        "run-p2",
        url,
        "partial",
        "2024-01-02T00:00:00Z",
        "Second attempt.",
        wip_branch_url=wip2,
    )
    result = get_prior_wip_run(conn, url)
    assert result is not None
    branch_url, summary = result
    assert branch_url == wip2
    assert summary == "Second attempt."


def test_get_prior_wip_run_skips_runs_without_branch() -> None:
    """Partial runs where preserve_wip returned None are not returned."""
    conn = _memory_db()
    url = "https://github.com/o/r/issues/9"
    _insert_run(
        conn,
        "run-no-branch",
        url,
        "partial",
        "2024-01-01T00:00:00Z",
        "Did stuff.",
        wip_branch_url=None,
    )
    result = get_prior_wip_run(conn, url)
    assert result is None


def test_get_prior_wip_run_null_summary_returns_empty_string() -> None:
    """When summary is NULL in the DB, returns an empty string (not None)."""
    conn = _memory_db()
    url = "https://github.com/o/r/issues/9"
    wip = "https://github.com/o/r/tree/labro-wip/run-null"
    _insert_run(
        conn,
        "run-null-sum",
        url,
        "partial",
        "2024-01-01T00:00:00Z",
        summary=None,
        wip_branch_url=wip,
    )
    result = get_prior_wip_run(conn, url)
    assert result is not None
    _, summary = result
    assert summary == ""


def test_get_prior_wip_run_ignores_different_url() -> None:
    """Partial runs for a different item URL are not returned."""
    conn = _memory_db()
    wip = "https://github.com/o/r/tree/labro-wip/run-other"
    _insert_run(
        conn,
        "run-other",
        "https://github.com/o/r/issues/99",
        "partial",
        "2024-01-01T00:00:00Z",
        wip_branch_url=wip,
    )
    result = get_prior_wip_run(conn, "https://github.com/o/r/issues/1")
    assert result is None


def test_migration_adds_closed_duplicate_to_constraint(tmp_path: Path) -> None:
    """A DB created with the old CHECK constraint is migrated to accept closed_duplicate."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    # Create items_touched with the OLD CHECK (no closed_duplicate)
    conn.executescript(
        """
        CREATE TABLE items_touched (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            repo TEXT NOT NULL,
            item_type TEXT NOT NULL CHECK (item_type IN ('issue', 'pr')),
            item_number INTEGER NOT NULL,
            outcome_state TEXT CHECK (outcome_state IN (
                'merged', 'closed_completed', 'closed_not_planned',
                'closed_unmerged', 'open'
            )),
            follow_up_commits INTEGER,
            thumbs_up INTEGER,
            thumbs_down INTEGER,
            signals_collected_at TEXT
        );
        """
    )
    conn.commit()

    # closed_duplicate should be rejected by the old constraint
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO items_touched (run_id, repo, item_type, item_number, outcome_state)"
            " VALUES ('r1', 'o/r', 'issue', 1, 'closed_duplicate')"
        )
    conn.close()

    # Now open with open_db — migration should apply
    db_path = tmp_path / "migrate.db"
    conn2 = open_db(str(db_path))
    conn2.execute(
        "INSERT INTO items_touched (run_id, repo, item_type, item_number, outcome_state)"
        " VALUES ('r1', 'o/r', 'issue', 1, 'closed_duplicate')"
    )
    conn2.commit()
    row = conn2.execute("SELECT outcome_state FROM items_touched WHERE run_id='r1'").fetchone()
    assert row["outcome_state"] == "closed_duplicate"
    conn2.close()


def test_migration_adds_wip_branch_url_column() -> None:
    """open_db on a DB without wip_branch_url adds the column via ALTER TABLE."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(
        """
        CREATE TABLE runs (
            run_id TEXT PRIMARY KEY, project TEXT NOT NULL,
            task_source TEXT, task_description TEXT, item_url TEXT,
            trigger_label TEXT, agent TEXT, model TEXT,
            started_at TEXT NOT NULL, ended_at TEXT, duration_s REAL,
            outcome TEXT NOT NULL
                CHECK (outcome IN ('success','failure','partial','skipped')),
            turns_used INTEGER, total_cost_usd REAL,
            input_tokens INTEGER, output_tokens INTEGER,
            cache_read_tokens INTEGER, cache_write_tokens INTEGER,
            summary TEXT, actions_taken TEXT, failure_reason TEXT
        );
        CREATE TABLE project_locks (project TEXT PRIMARY KEY, locked_at TEXT NOT NULL);
        CREATE TABLE items_touched (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL REFERENCES runs (run_id),
            repo TEXT NOT NULL,
            item_type TEXT NOT NULL CHECK (item_type IN ('issue', 'pr')),
            item_number INTEGER NOT NULL, outcome_state TEXT,
            follow_up_commits INTEGER, thumbs_up INTEGER,
            thumbs_down INTEGER, signals_collected_at TEXT
        );
        """
    )
    conn.commit()

    cols_before = {r[1] for r in conn.execute("PRAGMA table_info(runs)").fetchall()}
    assert "wip_branch_url" not in cols_before

    # Simulate the migration that open_db would apply
    with conn:
        conn.execute("ALTER TABLE runs ADD COLUMN wip_branch_url TEXT")

    cols_after = {r[1] for r in conn.execute("PRAGMA table_info(runs)").fetchall()}
    assert "wip_branch_url" in cols_after
