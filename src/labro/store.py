"""SQLite persistence layer for Labro run records and project locks.

Opens the database in WAL mode and manages the three core tables:
``runs``, ``project_locks``, and ``items_touched``.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

# ---------------------------------------------------------------------------
# Schema DDL (ARCHITECTURE.md section 8, lines 679-741)
# ---------------------------------------------------------------------------

_DDL = """\
CREATE TABLE IF NOT EXISTS runs (
    run_id              TEXT    PRIMARY KEY,
    project             TEXT    NOT NULL,
    task_source         TEXT,
    task_description    TEXT,
    item_url            TEXT,
    trigger_label       TEXT,
    agent               TEXT,
    provider            TEXT,
    model               TEXT,
    effort              TEXT,
    started_at          TEXT    NOT NULL,
    ended_at            TEXT,
    duration_s          REAL,
    outcome             TEXT    NOT NULL
                            CHECK (outcome IN ('success', 'failure', 'partial', 'skipped')),
    turns_used          INTEGER,
    total_cost_usd      REAL,
    input_tokens        INTEGER,
    output_tokens       INTEGER,
    cache_read_tokens   INTEGER,
    cache_write_tokens  INTEGER,
    summary             TEXT,
    actions_taken       TEXT,
    failure_reason      TEXT,
    wip_branch_url      TEXT,
    chosen_perspective  TEXT
);

CREATE INDEX IF NOT EXISTS idx_runs_project    ON runs (project);
CREATE INDEX IF NOT EXISTS idx_runs_started_at ON runs (started_at);
CREATE INDEX IF NOT EXISTS idx_runs_outcome    ON runs (outcome);

CREATE TABLE IF NOT EXISTS project_locks (
    project     TEXT    PRIMARY KEY,
    locked_at   TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS items_touched (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                  TEXT    NOT NULL    REFERENCES runs (run_id),
    repo                    TEXT    NOT NULL,
    item_type               TEXT    NOT NULL    CHECK (item_type IN ('issue', 'pr')),
    item_number             INTEGER NOT NULL,
    outcome_state           TEXT    CHECK (outcome_state IN (
                                        'merged',
                                        'closed_completed',
                                        'closed_not_planned',
                                        'closed_unmerged',
                                        'closed_duplicate',
                                        'open'
                                    )),
    follow_up_commits       INTEGER,
    thumbs_up               INTEGER,
    thumbs_down             INTEGER,
    signals_collected_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_items_touched_run_id ON items_touched (run_id);
CREATE INDEX IF NOT EXISTS idx_items_touched_repo_item
    ON items_touched (repo, item_type, item_number);
"""


def open_db(db_path: str | Path) -> sqlite3.Connection:
    """Open (or create) the SQLite database in WAL mode and apply the schema.

    Args:
        db_path: Filesystem path to the ``.db`` file, or ``":memory:"`` for tests.

    Returns:
        An open :class:`sqlite3.Connection` with WAL mode enabled and all
        tables / indexes created.
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_DDL)
    # Forward migration: add columns introduced after initial schema creation.
    try:
        conn.execute("ALTER TABLE runs ADD COLUMN chosen_perspective TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # column already exists on existing installs

    # Forward migration: widen items_touched.outcome_state CHECK constraint
    # to include 'closed_duplicate'. SQLite cannot ALTER CONSTRAINT, so we
    # recreate the table.
    conn.execute("SAVEPOINT migrate_closed_duplicate")
    try:
        conn.execute("ALTER TABLE items_touched RENAME TO items_touched_old")
        conn.execute(
            """
            CREATE TABLE items_touched (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id                  TEXT    NOT NULL    REFERENCES runs (run_id),
                repo                    TEXT    NOT NULL,
                item_type               TEXT    NOT NULL    CHECK (item_type IN ('issue', 'pr')),
                item_number             INTEGER NOT NULL,
                outcome_state           TEXT    CHECK (outcome_state IN (
                                                    'merged',
                                                    'closed_completed',
                                                    'closed_not_planned',
                                                    'closed_unmerged',
                                                    'closed_duplicate',
                                                    'open'
                                                )),
                follow_up_commits       INTEGER,
                thumbs_up               INTEGER,
                thumbs_down             INTEGER,
                signals_collected_at    TEXT
            )
            """
        )
        conn.execute("INSERT INTO items_touched SELECT * FROM items_touched_old")
        conn.execute("DROP TABLE items_touched_old")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_items_touched_run_id ON items_touched (run_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_items_touched_repo_item"
            " ON items_touched (repo, item_type, item_number)"
        )
        conn.execute("RELEASE migrate_closed_duplicate")
        conn.commit()
    except sqlite3.OperationalError:
        conn.execute("ROLLBACK TO migrate_closed_duplicate")

    return conn


def acquire_lock(conn: sqlite3.Connection, project: str, timeout_s: int) -> bool:
    """Attempt to acquire the run lock for *project*.

    Inserts a row into ``project_locks``.  If a non-stale lock already
    exists the function returns ``False`` immediately without touching the
    database.

    Stale detection: a lock whose age exceeds ``timeout_s + 60`` seconds is
    overwritten — the 60-second grace period prevents the race window where a
    previous run's ``finally`` block has not yet released the lock when a new
    cron tick fires.

    Args:
        conn: Open database connection.
        project: Project name (primary key in ``project_locks``).
        timeout_s: Agent subprocess timeout in seconds.

    Returns:
        ``True`` if the lock was acquired, ``False`` if a non-stale lock is
        held by another run.
    """
    stale_threshold_s = timeout_s + 60

    with conn:
        row = conn.execute(
            "SELECT locked_at FROM project_locks WHERE project = ?",
            (project,),
        ).fetchone()

        if row is not None:
            # Check staleness using SQLite's datetime arithmetic.
            is_stale: int = conn.execute(
                """
                SELECT (strftime('%s', 'now') - strftime('%s', ?)) > ?
                """,
                (row["locked_at"], stale_threshold_s),
            ).fetchone()[0]

            if not is_stale:
                return False

            # Stale — remove the old lock so we can INSERT fresh below.
            conn.execute(
                "DELETE FROM project_locks WHERE project = ?",
                (project,),
            )

        conn.execute(
            "INSERT INTO project_locks (project, locked_at)"
            " VALUES (?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))",
            (project,),
        )

    return True


def release_lock(conn: sqlite3.Connection, project: str) -> None:
    """Release the run lock for *project*.

    A no-op if no lock row exists (idempotent — safe to call in ``finally``
    even if ``acquire_lock`` was never called).

    Args:
        conn: Open database connection.
        project: Project name.
    """
    with conn:
        conn.execute(
            "DELETE FROM project_locks WHERE project = ?",
            (project,),
        )


def insert_items_touched(
    conn: sqlite3.Connection,
    run_id: str,
    repo: str,
    item_type: str,
    item_number: int,
) -> None:
    """Record a GitHub item that was acted on during *run_id*.

    Args:
        conn: Open database connection.
        run_id: Run identifier (FK into ``runs``).
        repo: ``owner/repo`` string.
        item_type: ``"issue"`` or ``"pr"``.
        item_number: GitHub item number.
    """
    conn.execute(
        "INSERT INTO items_touched (run_id, repo, item_type, item_number) VALUES (?, ?, ?, ?)",
        (run_id, repo, item_type, item_number),
    )
    conn.commit()


def get_items_for_signal_collection(
    conn: sqlite3.Connection,
    *,
    stale_days: int | None = None,
) -> list[sqlite3.Row]:
    """Return items_touched rows needing signal collection.

    Returns rows where ``signals_collected_at`` is NULL (never collected),
    or where the item was still open at last collection and is older than
    *stale_days* days (re-collect to catch state transitions like merges).

    Args:
        conn: Open database connection.
        stale_days: Re-collect open items not refreshed in this many days.
            ``None`` (default) skips the stale clause — only uncollected rows
            are returned.

    Returns:
        A list of :class:`sqlite3.Row` objects with columns ``id``, ``repo``,
        ``item_type``, ``item_number``, ``outcome_state``, ``started_at``.
    """
    if stale_days is None:
        return conn.execute(
            """
            SELECT it.id, it.repo, it.item_type, it.item_number, it.outcome_state,
                   r.started_at
            FROM items_touched it
            JOIN runs r ON it.run_id = r.run_id
            WHERE it.signals_collected_at IS NULL
            ORDER BY r.started_at DESC
            """,
        ).fetchall()

    return conn.execute(
        """
        SELECT it.id, it.repo, it.item_type, it.item_number, it.outcome_state,
               r.started_at
        FROM items_touched it
        JOIN runs r ON it.run_id = r.run_id
        WHERE it.signals_collected_at IS NULL
           OR (
               it.outcome_state = 'open'
               AND it.signals_collected_at < datetime('now', ?)
           )
        ORDER BY r.started_at DESC
        """,
        (f"-{stale_days} days",),
    ).fetchall()


def update_item_signals(
    conn: sqlite3.Connection,
    item_id: int,
    *,
    outcome_state: str | None,
    follow_up_commits: int | None,
    thumbs_up: int,
    thumbs_down: int,
    collected_at: str,
) -> None:
    """Back-fill the signal columns for a single items_touched row.

    Args:
        conn: Open database connection.
        item_id: Primary key of the ``items_touched`` row.
        outcome_state: The resolved outcome state (e.g. ``"merged"``, ``"open"``).
        follow_up_commits: Number of follow-up commits (PRs only; ``None`` for issues).
        thumbs_up: Count of +1 reactions.
        thumbs_down: Count of -1 reactions.
        collected_at: ISO 8601 UTC timestamp for the collection.
    """
    conn.execute(
        """
        UPDATE items_touched
        SET outcome_state=?, follow_up_commits=?, thumbs_up=?, thumbs_down=?,
            signals_collected_at=?
        WHERE id=?
        """,
        (outcome_state, follow_up_commits, thumbs_up, thumbs_down, collected_at, item_id),
    )
    conn.commit()


def get_prior_wip_run(conn: sqlite3.Connection, item_url: str) -> tuple[str, str] | None:
    """Return (wip_branch_url, summary) of the most recent partial run that has a preserved
    WIP branch for item_url, or None.

    Only returns rows where wip_branch_url IS NOT NULL so that partial runs where
    preserve_wip failed or was skipped are not mistakenly treated as resumable.

    @author Claude Sonnet 4.6 Anthropic
    """
    row = conn.execute(
        "SELECT wip_branch_url, summary FROM runs"
        " WHERE item_url = ? AND outcome = 'partial' AND wip_branch_url IS NOT NULL"
        " ORDER BY started_at DESC LIMIT 1",
        (item_url,),
    ).fetchone()
    if row is None:
        return None
    return row["wip_branch_url"], row["summary"] or ""


def list_locks(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return all rows from project_locks ordered by locked_at ASC.

    @author Claude Sonnet 4.6 Anthropic
    """
    return conn.execute(
        "SELECT project, locked_at FROM project_locks ORDER BY locked_at ASC"
    ).fetchall()


def query_runs(
    conn: sqlite3.Connection,
    *,
    project: str | None = None,
    outcome: str | None = None,
    limit: int = 20,
) -> list[sqlite3.Row]:
    """Return up to *limit* rows from runs (newest first) with optional filters.

    @author Claude Sonnet 4.6 Anthropic
    """
    clauses: list[str] = []
    params: list[str | int] = []
    if project is not None:
        clauses.append("project = ?")
        params.append(project)
    if outcome is not None:
        clauses.append("outcome = ?")
        params.append(outcome)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)
    # clauses are hardcoded strings — no user input in the WHERE clause.
    sql = (
        f"SELECT started_at, project, outcome, task_source, item_url, duration_s, "  # noqa: S608
        f"total_cost_usd, turns_used, summary, input_tokens, output_tokens, "
        f"cache_read_tokens, cache_write_tokens, provider, model "
        f"FROM runs {where} ORDER BY started_at DESC LIMIT ?"  # nosec B608
    )
    return conn.execute(sql, params).fetchall()


def get_daily_spend(conn: sqlite3.Connection, project: str) -> float:
    """Return the total cost in USD for *project* runs started today (UTC).

    Args:
        conn: Open database connection.
        project: Project name.

    Returns:
        Sum of ``total_cost_usd`` for rows where ``DATE(started_at)`` equals
        today's UTC date, or ``0.0`` if no rows match.
    """
    result: float = conn.execute(
        """
        SELECT COALESCE(SUM(total_cost_usd), 0.0)
        FROM runs
        WHERE project = ?
          AND DATE(started_at) = DATE('now')
        """,
        (project,),
    ).fetchone()[0]
    return result
