"""Tests for ``labro publish-db`` CLI subcommand.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import patch

import pytest

import labro.store as store_mod
from labro.cli import _cmd_publish_db
from labro.config.schema import (
    DashboardConfig,
    DefaultsConfig,
    DigestConfig,
    LabroConfig,
    ProjectConfig,
)
from labro.r2 import R2Credentials


@pytest.fixture(autouse=True)
def _r2_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set all four R2 vars so publish-db tests don't fail the startup env check."""
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "test-key-id")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "test-secret")
    monkeypatch.setenv("R2_ACCOUNT_ID", "test-acct")
    monkeypatch.setenv("R2_BUCKET", "test-bucket")


def _make_config(
    *,
    dashboard_enabled: bool = True,
    key_prefix: str = "",
    endpoint: str | None = "https://fake.r2.cloudflarestorage.com",
    projects: list[ProjectConfig] | None = None,
) -> LabroConfig:
    dashboard = DashboardConfig(
        enabled=dashboard_enabled,
        key_prefix=key_prefix,
        endpoint=endpoint,
    )
    if projects is None:
        projects = [
            ProjectConfig(name="test-project", repo="o/test", cron="0 * * * *", publish=True)
        ]
    return LabroConfig(
        digest=DigestConfig(enabled=False),
        dashboard=dashboard,
        defaults=DefaultsConfig(),
        projects=projects,
    )


def _make_db(
    tmp_path: Path,
    *,
    num_rows: int = 3,
    projects: dict[str, int] | None = None,
) -> Path:
    """Create a real labro.db at *tmp_path/labro.db*.

    If *projects* is provided (e.g. ``{"alpha": 2, "beta": 5}``), insert
    that many rows per project instead of using *num_rows*/*test-project*.
    """
    db_path = tmp_path / "labro.db"
    conn = store_mod.open_db(db_path)
    if projects:
        for project_name, count in projects.items():
            for i in range(count):
                conn.execute(
                    "INSERT INTO runs (run_id, project, started_at, outcome) VALUES (?, ?, ?, ?)",
                    (
                        f"run-{project_name}-{i}",
                        project_name,
                        "2024-01-01T00:00:00Z",
                        "success",
                    ),
                )
    else:
        for i in range(num_rows):
            conn.execute(
                "INSERT INTO runs (run_id, project, started_at, outcome) VALUES (?, ?, ?, ?)",
                (f"run-{i}", "test-project", "2024-01-01T00:00:00Z", "success"),
            )
    conn.commit()
    conn.close()
    return db_path


def _run(
    config: LabroConfig,
    db_path: Path,
    *,
    dry_run: bool = False,
    snapshot_path: Path | None = None,
) -> tuple[int, str, str]:
    """Invoke _cmd_publish_db and return (rc, stdout, stderr)."""
    args = argparse.Namespace(
        config=db_path.parent / "labro.toml",
        db_path=db_path,
        dry_run=dry_run,
        snapshot_path=snapshot_path,
    )
    import io
    import sys

    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout = io.StringIO()
    sys.stderr = io.StringIO()
    try:
        with patch("labro.cli.load_config", return_value=config):
            rc = _cmd_publish_db(args)
        return rc, sys.stdout.getvalue(), sys.stderr.getvalue()
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr


# ── dry-run ────────────────────────────────────────────────────────────────────


def test_dry_run_prints_manifest(tmp_path: Path) -> None:
    """--dry-run prints snapshot path + db_key + manifest JSON; no upload."""
    db_path = _make_db(tmp_path, num_rows=5)
    config = _make_config()

    with patch("labro.r2._put_object") as mock_put:
        rc, stdout, _ = _run(config, db_path, dry_run=True)

    assert rc == 0
    assert "snapshot:" in stdout
    assert "db_key:" in stdout
    assert '"schema_version": 1' in stdout
    assert '"row_count": 5' in stdout
    mock_put.assert_not_called()


def test_dry_run_no_creds_needed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--dry-run succeeds even when R2_* env vars are absent."""
    monkeypatch.delenv("R2_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("R2_SECRET_ACCESS_KEY", raising=False)
    monkeypatch.delenv("R2_ACCOUNT_ID", raising=False)

    db_path = _make_db(tmp_path)
    config = _make_config()

    rc, _stdout, _ = _run(config, db_path, dry_run=True)
    assert rc == 0


# ── live upload path ───────────────────────────────────────────────────────────


_FAKE_CREDS = R2Credentials(
    access_key_id="test-key-id",
    secret_access_key="test-secret",  # noqa: S106
    account_id="test-acct",
    endpoint="https://fake.r2.example.com",
)


def test_live_upload_two_calls_correct_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Live path calls _put_object twice: db first, manifest second."""
    monkeypatch.setenv("R2_BUCKET", "my-bucket")
    db_path = _make_db(tmp_path, num_rows=2)
    config = _make_config(endpoint="https://fake.r2.example.com")

    with (
        patch("labro.r2._put_object") as mock_put,
        patch("labro.r2.credentials_from_env", return_value=_FAKE_CREDS),
    ):
        rc, _, _ = _run(config, db_path)

    assert rc == 0
    assert mock_put.call_count == 2

    db_call, manifest_call = mock_put.call_args_list
    # DB object key starts with "db/"
    assert db_call.kwargs["key"].startswith("db/labro-")
    assert db_call.kwargs["bucket"] == "my-bucket"
    assert db_call.kwargs["content_type"] == "application/octet-stream"
    assert "immutable" in db_call.kwargs["cache_control"]

    # Manifest key
    assert manifest_call.kwargs["key"] == "manifest.json"
    assert manifest_call.kwargs["bucket"] == "my-bucket"
    assert manifest_call.kwargs["content_type"] == "application/json"
    assert "must-revalidate" in manifest_call.kwargs["cache_control"]


def test_live_upload_manifest_content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Manifest JSON contains expected fields with correct row_count."""
    monkeypatch.setenv("R2_BUCKET", "test-bucket")
    db_path = _make_db(tmp_path, num_rows=7)
    config = _make_config()

    captured_manifest: list[bytes] = []

    def _capture(**kwargs: object) -> None:
        if kwargs.get("key") == "manifest.json":
            captured_manifest.append(kwargs["body"])  # type: ignore[arg-type]

    with (
        patch("labro.r2._put_object", side_effect=_capture),
        patch("labro.r2.credentials_from_env", return_value=_FAKE_CREDS),
    ):
        rc, _, _ = _run(config, db_path)

    assert rc == 0
    assert captured_manifest
    manifest = json.loads(captured_manifest[0])
    assert manifest["schema_version"] == 1
    assert manifest["row_count"] == 7
    assert manifest["db_filename"].startswith("db/labro-")
    assert len(manifest["content_hash"]) == 64  # sha256 hex
    assert manifest["size_bytes"] > 0
    assert "T" in manifest["generated_at"]


def test_live_key_prefix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """key_prefix is prepended to the db object key."""
    monkeypatch.setenv("R2_BUCKET", "test-bucket")
    db_path = _make_db(tmp_path)
    config = _make_config(key_prefix="prod/")

    db_keys: list[str] = []

    def _capture(**kwargs: object) -> None:
        key = kwargs.get("key", "")
        assert isinstance(key, str)
        if key != "manifest.json":
            db_keys.append(key)

    with (
        patch("labro.r2._put_object", side_effect=_capture),
        patch("labro.r2.credentials_from_env", return_value=_FAKE_CREDS),
    ):
        rc, _, _ = _run(config, db_path)

    assert rc == 0
    assert db_keys[0].startswith("prod/db/labro-")


# ── disabled / missing db ──────────────────────────────────────────────────────


def test_disabled_returns_zero_no_upload(tmp_path: Path) -> None:
    """dashboard.enabled = false → return 0 immediately, no upload."""
    db_path = _make_db(tmp_path)
    config = _make_config(dashboard_enabled=False)

    with patch("labro.r2._put_object") as mock_put:
        rc, _, _ = _run(config, db_path)

    assert rc == 0
    mock_put.assert_not_called()


def test_missing_db_returns_zero(tmp_path: Path) -> None:
    """Missing DB → return 0 with a warning; no upload."""
    db_path = tmp_path / "nonexistent.db"
    config = _make_config()

    with patch("labro.r2._put_object") as mock_put:
        rc, _, _ = _run(config, db_path)

    assert rc == 0
    mock_put.assert_not_called()


# ── missing credentials ────────────────────────────────────────────────────────


def test_missing_creds_returns_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing R2_* creds → return 1 with error message."""
    monkeypatch.delenv("R2_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("R2_SECRET_ACCESS_KEY", raising=False)
    monkeypatch.delenv("R2_ACCOUNT_ID", raising=False)

    db_path = _make_db(tmp_path)
    config = _make_config()

    rc, _, stderr = _run(config, db_path)
    assert rc == 1
    assert "R2" in stderr or "missing" in stderr.lower()


# ── upload failure ─────────────────────────────────────────────────────────────


def test_upload_failure_returns_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Upload RuntimeError → return 1; temp snapshot cleaned up."""
    monkeypatch.setenv("R2_BUCKET", "test-bucket")
    db_path = _make_db(tmp_path)
    config = _make_config()

    with (
        patch("labro.r2._put_object", side_effect=RuntimeError("HTTP 403")),
        patch("labro.r2.credentials_from_env", return_value=_FAKE_CREDS),
    ):
        rc, _, stderr = _run(config, db_path)

    assert rc == 1
    assert "upload failed" in stderr

    # Temp snapshot must be cleaned up
    stale = list(tmp_path.glob(".labro-snapshot-*.db"))
    assert stale == []


# ── snapshot path kept when --snapshot-path given ─────────────────────────────


def test_snapshot_path_kept(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--snapshot-path file is NOT deleted after a successful upload."""
    monkeypatch.setenv("R2_BUCKET", "test-bucket")
    db_path = _make_db(tmp_path)
    snapshot_path = tmp_path / "my-snapshot.db"
    config = _make_config()

    with (
        patch("labro.r2._put_object"),
        patch("labro.r2.credentials_from_env", return_value=_FAKE_CREDS),
    ):
        rc, _, _ = _run(config, db_path, snapshot_path=snapshot_path)

    assert rc == 0
    assert snapshot_path.exists()


# ── per-project publish gate ─────────────────────────────────────────────────


def _extract_row_counts(snapshot_path: Path) -> dict[str, int]:
    """Return a dict of table → row count from a snapshot DB."""
    import sqlite3

    conn = sqlite3.connect(str(snapshot_path))
    counts = {}
    for table in ("runs", "items_touched", "projects"):
        counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608
    conn.close()
    return counts


def test_no_projects_published_empty_snapshot(tmp_path: Path) -> None:
    """When no project has publish=true, the snapshot has zero rows."""
    db_path = _make_db(tmp_path, projects={"alpha": 3, "beta": 2})
    snapshot_path = tmp_path / "snapshot.db"
    config = _make_config(
        projects=[
            ProjectConfig(name="alpha", repo="o/alpha", cron="0 * * * *", publish=False),
            ProjectConfig(name="beta", repo="o/beta", cron="0 * * * *", publish=False),
        ]
    )

    rc, _, _ = _run(config, db_path, dry_run=True, snapshot_path=snapshot_path)
    assert rc == 0
    counts = _extract_row_counts(snapshot_path)
    assert counts["runs"] == 0
    assert counts["projects"] == 0


def test_mixed_publish_flags_filters_correctly(tmp_path: Path) -> None:
    """Only runs from published projects appear in the snapshot."""
    db_path = _make_db(tmp_path, projects={"published": 4, "private": 6})
    snapshot_path = tmp_path / "snapshot.db"
    config = _make_config(
        projects=[
            ProjectConfig(name="published", repo="o/pub", cron="0 * * * *", publish=True),
            ProjectConfig(name="private", repo="o/priv", cron="0 * * * *", publish=False),
        ]
    )

    rc, _, _ = _run(config, db_path, dry_run=True, snapshot_path=snapshot_path)
    assert rc == 0
    counts = _extract_row_counts(snapshot_path)
    assert counts["runs"] == 4
    assert counts["projects"] == 1


def test_all_published_keeps_all_rows(tmp_path: Path) -> None:
    """When all projects have publish=true, all runs are kept."""
    db_path = _make_db(tmp_path, projects={"a": 3, "b": 2})
    snapshot_path = tmp_path / "snapshot.db"
    config = _make_config(
        projects=[
            ProjectConfig(name="a", repo="o/a", cron="0 * * * *", publish=True),
            ProjectConfig(name="b", repo="o/b", cron="0 * * * *", publish=True),
        ]
    )

    rc, _, _ = _run(config, db_path, dry_run=True, snapshot_path=snapshot_path)
    assert rc == 0
    counts = _extract_row_counts(snapshot_path)
    assert counts["runs"] == 5
    assert counts["projects"] == 2


def test_items_touched_filtered_with_runs(tmp_path: Path) -> None:
    """items_touched rows for unpublished runs are removed."""
    import sqlite3

    db_path = tmp_path / "labro.db"
    conn = store_mod.open_db(db_path)
    conn.execute(
        "INSERT INTO runs (run_id, project, started_at, outcome) VALUES (?, ?, ?, ?)",
        ("run-pub", "published", "2024-01-01T00:00:00Z", "success"),
    )
    conn.execute(
        "INSERT INTO runs (run_id, project, started_at, outcome) VALUES (?, ?, ?, ?)",
        ("run-priv", "private", "2024-01-01T00:00:00Z", "success"),
    )
    conn.execute(
        "INSERT INTO items_touched (run_id, repo, item_type, item_number) VALUES (?, ?, ?, ?)",
        ("run-pub", "o/pub", "issue", 1),
    )
    conn.execute(
        "INSERT INTO items_touched (run_id, repo, item_type, item_number) VALUES (?, ?, ?, ?)",
        ("run-priv", "o/priv", "issue", 2),
    )
    conn.commit()
    conn.close()

    snapshot_path = tmp_path / "snapshot.db"
    config = _make_config(
        projects=[
            ProjectConfig(name="published", repo="o/pub", cron="0 * * * *", publish=True),
            ProjectConfig(name="private", repo="o/priv", cron="0 * * * *", publish=False),
        ]
    )

    rc, _, _ = _run(config, db_path, dry_run=True, snapshot_path=snapshot_path)
    assert rc == 0

    snap_conn = sqlite3.connect(str(snapshot_path))
    runs = snap_conn.execute("SELECT run_id FROM runs").fetchall()
    items = snap_conn.execute("SELECT run_id FROM items_touched").fetchall()
    snap_conn.close()

    assert len(runs) == 1
    assert runs[0][0] == "run-pub"
    assert len(items) == 1
    assert items[0][0] == "run-pub"


def test_publish_gate_updates_manifest_row_count(tmp_path: Path) -> None:
    """Manifest row_count reflects only published runs, not total DB rows."""
    db_path = _make_db(tmp_path, projects={"pub": 3, "priv": 7})
    config = _make_config(
        projects=[
            ProjectConfig(name="pub", repo="o/pub", cron="0 * * * *", publish=True),
            ProjectConfig(name="priv", repo="o/priv", cron="0 * * * *", publish=False),
        ]
    )

    captured_manifest: list[bytes] = []

    def _capture(**kwargs: object) -> None:
        if kwargs.get("key") == "manifest.json":
            captured_manifest.append(kwargs["body"])  # type: ignore[arg-type]

    with (
        patch("labro.r2._put_object", side_effect=_capture),
        patch("labro.r2.credentials_from_env", return_value=_FAKE_CREDS),
    ):
        rc, _, _ = _run(config, db_path)

    assert rc == 0
    manifest = json.loads(captured_manifest[0])
    assert manifest["row_count"] == 3


def test_unpublished_free_text_absent_from_raw_snapshot_bytes(tmp_path: Path) -> None:
    """Deleted rows must leave no residue in the snapshot's raw bytes.

    SQLite ``DELETE`` only frees pages; without a VACUUM the deleted row
    content (agent free-text, private repo/project names) stays physically
    present in the file and is recoverable from the uploaded snapshot.
    Assert at the byte level rather than via SQL, which cannot see the
    difference.

    @author Claude Opus 4.8 Anthropic
    """
    secret_marker = "SUPER-SECRET-PRIVATE-SUMMARY-9f3a"  # noqa: S105  # test fixture, not a credential
    db_path = tmp_path / "labro.db"
    conn = store_mod.open_db(db_path)
    conn.execute(
        "INSERT INTO runs (run_id, project, started_at, outcome, summary) VALUES (?, ?, ?, ?, ?)",
        ("run-pub", "published", "2024-01-01T00:00:00Z", "success", "public summary"),
    )
    conn.execute(
        "INSERT INTO runs (run_id, project, started_at, outcome, summary) VALUES (?, ?, ?, ?, ?)",
        ("run-priv", "private-repo-name", "2024-01-01T00:00:00Z", "success", secret_marker),
    )
    conn.execute(
        "INSERT INTO project_locks (project, locked_at) VALUES (?, ?)",
        ("private-repo-name", "2024-01-01T00:00:00Z"),
    )
    conn.commit()
    conn.close()

    snapshot_path = tmp_path / "snapshot.db"
    config = _make_config(
        projects=[
            ProjectConfig(name="published", repo="o/pub", cron="0 * * * *", publish=True),
            ProjectConfig(
                name="private-repo-name", repo="o/priv", cron="0 * * * *", publish=False
            ),
        ]
    )

    rc, _, _ = _run(config, db_path, dry_run=True, snapshot_path=snapshot_path)
    assert rc == 0

    raw = snapshot_path.read_bytes()
    assert secret_marker.encode() not in raw
    assert b"private-repo-name" not in raw
