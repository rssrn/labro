"""Tests for ``labro collect-signals`` CLI command.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

from labro.signals import ItemSignals
from labro.store import open_db


def _populate(conn: sqlite3.Connection) -> None:
    """Insert a run and two items_touched rows for testing."""
    conn.execute(
        "INSERT INTO runs (run_id, project, started_at, outcome)"
        " VALUES ('run-1', 'proj', '2024-01-15T10:00:00Z', 'success')"
    )
    conn.execute(
        "INSERT INTO items_touched (run_id, repo, item_type, item_number)"
        " VALUES ('run-1', 'org/repo', 'issue', 1)"
    )
    conn.execute(
        "INSERT INTO items_touched (run_id, repo, item_type, item_number)"
        " VALUES ('run-1', 'org/repo', 'pr', 2)"
    )
    conn.commit()


def test_dry_run_no_writes(tmp_path: Path) -> None:
    """With --dry-run, update_item_signals is not called."""
    db_path = tmp_path / "test.db"
    conn = open_db(str(db_path))
    _populate(conn)
    conn.close()

    from labro.cli import _build_parser

    parser = _build_parser()
    with patch("labro.cli.signals_mod.collect") as mock_collect:
        mock_collect.return_value = ItemSignals(
            outcome_state="closed_completed",
            follow_up_commits=None,
            thumbs_up=2,
            thumbs_down=0,
        )
        args = parser.parse_args(["collect-signals", "--db-path", str(db_path), "--dry-run"])
        exit_code = args.func(args)

    assert exit_code == 0
    mock_collect.assert_called()

    # DB should have NULL signals (no writes happened)
    conn2 = open_db(str(db_path))
    row = conn2.execute(
        "SELECT outcome_state FROM items_touched WHERE repo='org/repo' AND item_number=1"
    ).fetchone()
    assert row["outcome_state"] is None
    conn2.close()


def test_updates_written_on_success(tmp_path: Path) -> None:
    """Without --dry-run, update_item_signals is called and DB is updated."""
    db_path = tmp_path / "test.db"
    conn = open_db(str(db_path))
    _populate(conn)
    conn.close()

    from labro.cli import _build_parser

    parser = _build_parser()
    with patch("labro.cli.signals_mod.collect") as mock_collect:
        mock_collect.return_value = ItemSignals(
            outcome_state="merged",
            follow_up_commits=3,
            thumbs_up=5,
            thumbs_down=1,
        )
        args = parser.parse_args(
            ["collect-signals", "--db-path", str(db_path), "--stale-days", "0"]
        )
        exit_code = args.func(args)

    assert exit_code == 0

    conn2 = open_db(str(db_path))
    rows = conn2.execute(
        "SELECT outcome_state, thumbs_up, thumbs_down, signals_collected_at"
        " FROM items_touched WHERE repo='org/repo'"
    ).fetchall()
    assert len(rows) == 2
    for row in rows:
        assert row["outcome_state"] == "merged"
        assert row["thumbs_up"] == 5
        assert row["thumbs_down"] == 1
        assert row["signals_collected_at"] is not None
    conn2.close()


def test_error_on_one_item_continues(tmp_path: Path) -> None:
    """A CalledProcessError on one row does not stop processing of remaining rows."""
    from subprocess import CalledProcessError

    db_path = tmp_path / "test.db"
    conn = open_db(str(db_path))
    _populate(conn)
    conn.close()

    from labro.cli import _build_parser

    parser = _build_parser()

    call_count = 0

    def _collect_side_effect(
        repo: str,
        item_type: str,
        item_number: int,
        run_started_at: str,
        bot_username: str | None = None,
    ) -> ItemSignals:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise CalledProcessError(1, ["gh", "api", "dummy"])
        return ItemSignals(
            outcome_state="open",
            follow_up_commits=None,
            thumbs_up=0,
            thumbs_down=0,
        )

    with patch("labro.cli.signals_mod.collect", side_effect=_collect_side_effect):
        args = parser.parse_args(
            ["collect-signals", "--db-path", str(db_path), "--stale-days", "0"]
        )
        exit_code = args.func(args)

    assert exit_code == 0
    # Both items were processed (one failed, one succeeded)
    assert call_count == 2


def test_duplicate_item_collected_once(tmp_path: Path) -> None:
    """Same repo/item touched in two runs is processed once, both rows updated."""
    db_path = tmp_path / "test.db"
    conn = open_db(str(db_path))
    conn.execute(
        "INSERT INTO runs (run_id, project, started_at, outcome)"
        " VALUES ('run-1', 'proj', '2024-01-15T10:00:00Z', 'success')"
    )
    conn.execute(
        "INSERT INTO runs (run_id, project, started_at, outcome)"
        " VALUES ('run-2', 'proj', '2024-01-16T10:00:00Z', 'success')"
    )
    # Same issue touched in both runs
    conn.execute(
        "INSERT INTO items_touched (run_id, repo, item_type, item_number)"
        " VALUES ('run-1', 'org/repo', 'issue', 1)"
    )
    conn.execute(
        "INSERT INTO items_touched (run_id, repo, item_type, item_number)"
        " VALUES ('run-2', 'org/repo', 'issue', 1)"
    )
    conn.commit()
    conn.close()

    from labro.cli import _build_parser

    parser = _build_parser()
    collect_call_count = 0

    def _collect_side_effect(
        repo: str,
        item_type: str,
        item_number: int,
        run_started_at: str,
        bot_username: str | None = None,
    ) -> ItemSignals:
        nonlocal collect_call_count
        collect_call_count += 1
        return ItemSignals(
            outcome_state="closed_completed",
            follow_up_commits=None,
            thumbs_up=1,
            thumbs_down=0,
        )

    with patch("labro.cli.signals_mod.collect", side_effect=_collect_side_effect):
        args = parser.parse_args(["collect-signals", "--db-path", str(db_path)])
        exit_code = args.func(args)

    assert exit_code == 0
    # collect() called exactly once despite two rows
    assert collect_call_count == 1

    conn2 = open_db(str(db_path))
    rows = conn2.execute(
        "SELECT signals_collected_at, outcome_state FROM items_touched WHERE repo='org/repo'"
    ).fetchall()
    assert len(rows) == 2
    # Both rows written (not just one)
    assert all(r["signals_collected_at"] is not None for r in rows)
    assert all(r["outcome_state"] == "closed_completed" for r in rows)
    conn2.close()
