"""Tests for M5 operator CLI subcommands: init, check, review, list-locks, unlock.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

import labro.store as store_mod
from labro.agents.claude_code import _check_anthropic_api_key
from labro.cli import (
    _cmd_check,
    _cmd_init,
    _cmd_list_locks,
    _cmd_review,
    _cmd_unlock,
    _collect_labels_for_project,
)
from labro.config.schema import (
    ActorRule,
    GhLabelSource,
    LabelRule,
    LabroConfig,
    ProjectConfig,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_label_rule(label: str = "ai-dev", done_label: str = "ai-dev-done") -> LabelRule:
    return LabelRule(label=label, done_label=done_label)


def _make_actor_rule(done_label: str = "ai-actor-done") -> ActorRule:
    return ActorRule(actor="dependabot[bot]", done_label=done_label)


def _make_gh_label_source(
    label_rules: list[LabelRule] | None = None,
    actor_rules: list[ActorRule] | None = None,
) -> GhLabelSource:
    return GhLabelSource(
        type="gh-label",
        label_rules=label_rules or [_make_label_rule()],
        actor_rules=actor_rules or [],
    )


def _make_project(
    name: str = "my-project",
    repo: str = "owner/repo",
    task_sources: list[Any] | None = None,
) -> ProjectConfig:
    return ProjectConfig(
        name=name,
        repo=repo,
        cron="0 * * * *",
        task_sources=task_sources or [_make_gh_label_source()],
    )


def _make_config(
    projects: list[ProjectConfig] | None = None,
) -> LabroConfig:
    return LabroConfig(
        projects=projects or [_make_project()],
    )


def _memory_db() -> sqlite3.Connection:
    return store_mod.open_db(":memory:")


def _make_args(**kwargs: Any) -> argparse.Namespace:
    defaults: dict[str, Any] = {
        "config": Path("labro.toml"),
        "db_path": Path("/data/labro.db"),
        "project": None,
        "outcome": None,
        "limit": 20,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _make_gh_result(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


# ---------------------------------------------------------------------------
# _collect_labels_for_project
# ---------------------------------------------------------------------------


def test_collect_labels_always_includes_fixed_labels() -> None:
    project = _make_project(task_sources=[])
    config = _make_config(projects=[project])
    labels = _collect_labels_for_project(project, config)
    assert "ai-failed" in labels
    assert "ai-contributed" in labels


def test_collect_labels_from_label_rules() -> None:
    source = _make_gh_label_source(label_rules=[_make_label_rule("ai-dev", "ai-dev-done")])
    project = _make_project(task_sources=[source])
    config = _make_config(projects=[project])
    labels = _collect_labels_for_project(project, config)
    assert "ai-dev" in labels
    assert "ai-dev-done" in labels


def test_collect_labels_from_actor_rules() -> None:
    source = _make_gh_label_source(
        label_rules=[_make_label_rule()],
        actor_rules=[_make_actor_rule("ai-actor-done")],
    )
    project = _make_project(task_sources=[source])
    config = _make_config(projects=[project])
    labels = _collect_labels_for_project(project, config)
    assert "ai-actor-done" in labels


def test_collect_labels_deduplication() -> None:
    source = _make_gh_label_source(
        label_rules=[
            _make_label_rule("ai-dev", "ai-dev-done"),
            _make_label_rule("ai-dev", "ai-dev-done"),
        ]
    )
    project = _make_project(task_sources=[source])
    config = _make_config(projects=[project])
    labels = _collect_labels_for_project(project, config)
    assert labels.count("ai-dev") == 1
    assert labels.count("ai-dev-done") == 1


# ---------------------------------------------------------------------------
# _cmd_init
# ---------------------------------------------------------------------------


def test_init_calls_gh_for_each_label(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _make_config()
    with (
        patch("labro.cli.load_config", return_value=config),
        patch("labro.cli._run_gh", return_value=_make_gh_result()) as mock_gh,
    ):
        result = _cmd_init(_make_args())
    assert result == 0
    called_labels = [call.args[0][3] for call in mock_gh.call_args_list]
    assert "ai-failed" in called_labels
    assert "ai-contributed" in called_labels
    assert "ai-dev" in called_labels
    assert "ai-dev-done" in called_labels


def test_init_project_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    p1 = _make_project("proj-a", "owner/repo-a")
    p2 = _make_project("proj-b", "owner/repo-b")
    config = _make_config(projects=[p1, p2])
    with (
        patch("labro.cli.load_config", return_value=config),
        patch("labro.cli._run_gh", return_value=_make_gh_result()) as mock_gh,
    ):
        result = _cmd_init(_make_args(project="proj-a"))
    assert result == 0
    repos_used = {call.args[0][5] for call in mock_gh.call_args_list}
    assert repos_used == {"owner/repo-a"}


def test_init_unknown_project_exits_1() -> None:
    config = _make_config()
    with (
        patch("labro.cli.load_config", return_value=config),
        patch("labro.cli._run_gh"),
    ):
        result = _cmd_init(_make_args(project="does-not-exist"))
    assert result == 1


def test_init_gh_failure_exits_1_and_continues() -> None:
    config = _make_config()
    # First label fails, rest succeed
    side_effects = [_make_gh_result(returncode=1, stderr="network error")] + [
        _make_gh_result()
    ] * 10
    with (
        patch("labro.cli.load_config", return_value=config),
        patch("labro.cli._run_gh", side_effect=side_effects) as mock_gh,
    ):
        result = _cmd_init(_make_args())
    assert result == 1
    # All labels were still attempted despite the first failure
    assert mock_gh.call_count > 1


def test_init_all_success_exits_0() -> None:
    config = _make_config()
    with (
        patch("labro.cli.load_config", return_value=config),
        patch("labro.cli._run_gh", return_value=_make_gh_result()),
    ):
        result = _cmd_init(_make_args())
    assert result == 0


def test_init_config_error_exits_1() -> None:
    from labro.config.loader import ConfigError

    with patch("labro.cli.load_config", side_effect=ConfigError("bad config")):
        result = _cmd_init(_make_args())
    assert result == 1


# ---------------------------------------------------------------------------
# _check_anthropic_api_key
# ---------------------------------------------------------------------------


def test_check_anthropic_api_key_valid() -> None:
    import urllib.request
    from unittest.mock import MagicMock

    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    with patch.object(urllib.request, "urlopen", return_value=mock_resp):
        status, msg = _check_anthropic_api_key("sk-valid")
    assert status == "OK  "
    assert "/v1/models" in msg


def test_check_anthropic_api_key_invalid() -> None:
    import urllib.error
    import urllib.request

    exc = urllib.error.HTTPError(None, 401, "Unauthorized", {}, None)  # type: ignore[arg-type]
    with patch.object(urllib.request, "urlopen", side_effect=exc):
        status, msg = _check_anthropic_api_key("sk-bad")
    assert status == "FAIL"
    assert "401" in msg


def test_check_anthropic_api_key_network_error() -> None:
    import urllib.request

    with patch.object(urllib.request, "urlopen", side_effect=OSError("timeout")):
        status, msg = _check_anthropic_api_key("sk-any")
    assert status == "WARN"
    assert "api.anthropic.com" in msg


# ---------------------------------------------------------------------------
# _cmd_check
# ---------------------------------------------------------------------------


def test_check_config_error_exits_1() -> None:
    from labro.config.loader import ConfigError

    with patch("labro.cli.load_config", side_effect=ConfigError("bad")):
        result = _cmd_check(_make_args())
    assert result == 1


def _check_gh_router(
    label_json: str,
    *,
    auth_ok: bool = True,
    label_list_ok: bool = True,
) -> Any:
    """Return a _run_gh side-effect that routes by command for _cmd_check tests."""

    def _route(cmd: list[str]) -> MagicMock:
        if "auth" in cmd:
            return _make_gh_result() if auth_ok else _make_gh_result(1, stderr="not authenticated")
        # label list
        if label_list_ok:
            return _make_gh_result(stdout=label_json)
        return _make_gh_result(returncode=1, stderr="gh error")

    return _route


_API_KEY_OK = ("OK  ", "ANTHROPIC_API_KEY: valid (GET /v1/models succeeded)")
_API_KEY_FAIL = ("FAIL", "ANTHROPIC_API_KEY: invalid or expired (401 Unauthorized)")


def _mock_agent(validate_result: tuple[str, str]) -> MagicMock:
    """Return a mock Agent whose validate_auth returns *validate_result*."""
    mock = MagicMock()
    mock.validate_auth.return_value = validate_result
    return mock


def test_check_missing_env_var_reported_as_fail(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("GH_TOKEN", raising=False)
    config = _make_config()
    all_labels = _collect_labels_for_project(config.projects[0], config)
    label_json = json.dumps([{"name": lbl} for lbl in all_labels])
    with (
        patch("labro.cli.load_config", return_value=config),
        patch("labro.cli.required_env_vars", return_value=["GH_TOKEN"]),
        patch("labro.cli.referenced_agents", return_value={"claude-code"}),
        patch("labro.cli.get_agent", return_value=_mock_agent(_API_KEY_OK)),
        patch("labro.cli._run_gh", side_effect=_check_gh_router(label_json)),
    ):
        result = _cmd_check(_make_args())
    assert result == 1
    out = capsys.readouterr().out
    assert "FAIL" in out
    assert "GH_TOKEN" in out


def test_check_missing_claude_auth_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _make_config()
    all_labels = _collect_labels_for_project(config.projects[0], config)
    label_json = json.dumps([{"name": lbl} for lbl in all_labels])
    _auth_fail = ("FAIL", "no Claude auth — set ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN")
    with (
        patch("labro.cli.load_config", return_value=config),
        patch("labro.cli.required_env_vars", return_value=[]),
        patch("labro.cli.referenced_agents", return_value={"claude-code"}),
        patch("labro.cli.get_agent", return_value=_mock_agent(_auth_fail)),
        patch("labro.cli._run_gh", side_effect=_check_gh_router(label_json)),
    ):
        result = _cmd_check(_make_args())
    assert result == 1
    out = capsys.readouterr().out
    assert "FAIL" in out
    assert "Claude auth" in out


def test_check_anthropic_api_key_invalid_reported_as_fail(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _make_config()
    all_labels = _collect_labels_for_project(config.projects[0], config)
    label_json = json.dumps([{"name": lbl} for lbl in all_labels])
    with (
        patch("labro.cli.load_config", return_value=config),
        patch("labro.cli.required_env_vars", return_value=[]),
        patch("labro.cli.referenced_agents", return_value={"claude-code"}),
        patch("labro.cli.get_agent", return_value=_mock_agent(_API_KEY_FAIL)),
        patch("labro.cli._run_gh", side_effect=_check_gh_router(label_json)),
    ):
        result = _cmd_check(_make_args())
    assert result == 1
    out = capsys.readouterr().out
    assert "FAIL" in out
    assert "ANTHROPIC_API_KEY" in out


def test_check_gh_auth_failure_reported_as_fail(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _make_config()
    all_labels = _collect_labels_for_project(config.projects[0], config)
    label_json = json.dumps([{"name": lbl} for lbl in all_labels])
    with (
        patch("labro.cli.load_config", return_value=config),
        patch("labro.cli.required_env_vars", return_value=[]),
        patch("labro.cli.referenced_agents", return_value={"claude-code"}),
        patch("labro.cli.get_agent", return_value=_mock_agent(_API_KEY_OK)),
        patch("labro.cli._run_gh", side_effect=_check_gh_router(label_json, auth_ok=False)),
    ):
        result = _cmd_check(_make_args())
    assert result == 1
    out = capsys.readouterr().out
    assert "FAIL" in out
    assert "gh auth status" in out


def test_check_missing_label_reported_as_fail(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _make_config()
    with (
        patch("labro.cli.load_config", return_value=config),
        patch("labro.cli.required_env_vars", return_value=[]),
        patch("labro.cli.referenced_agents", return_value={"claude-code"}),
        patch("labro.cli.get_agent", return_value=_mock_agent(_API_KEY_OK)),
        patch("labro.cli._run_gh", side_effect=_check_gh_router("[]")),
    ):
        result = _cmd_check(_make_args())
    assert result == 1
    out = capsys.readouterr().out
    assert "FAIL" in out
    assert "label missing" in out


def test_check_all_ok_exits_0(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _make_config()
    all_labels = _collect_labels_for_project(config.projects[0], config)
    label_json = json.dumps([{"name": lbl} for lbl in all_labels])
    with (
        patch("labro.cli.load_config", return_value=config),
        patch("labro.cli.required_env_vars", return_value=[]),
        patch("labro.cli.referenced_agents", return_value={"claude-code"}),
        patch("labro.cli.get_agent", return_value=_mock_agent(_API_KEY_OK)),
        patch("labro.cli._run_gh", side_effect=_check_gh_router(label_json)),
    ):
        result = _cmd_check(_make_args())
    assert result == 0
    out = capsys.readouterr().out
    assert "FAIL" not in out


def test_check_gh_label_list_failure_is_fail(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    config = _make_config()
    with (
        patch("labro.cli.load_config", return_value=config),
        patch("labro.cli.required_env_vars", return_value=[]),
        patch("labro.cli.referenced_agents", return_value={"claude-code"}),
        patch("labro.cli.get_agent", return_value=_mock_agent(_API_KEY_OK)),
        patch("labro.cli._run_gh", side_effect=_check_gh_router("[]", label_list_ok=False)),
    ):
        result = _cmd_check(_make_args())
    assert result == 1
    out = capsys.readouterr().out
    assert "FAIL" in out


# ---------------------------------------------------------------------------
# store.list_locks / store.query_runs
# ---------------------------------------------------------------------------


def test_list_locks_empty() -> None:
    conn = _memory_db()
    assert store_mod.list_locks(conn) == []


def test_list_locks_returns_rows() -> None:
    conn = _memory_db()
    with conn:
        conn.execute("INSERT INTO project_locks VALUES (?, ?)", ("proj-a", "2024-01-15T10:00:00Z"))
        conn.execute("INSERT INTO project_locks VALUES (?, ?)", ("proj-b", "2024-01-15T11:00:00Z"))
    rows = store_mod.list_locks(conn)
    assert len(rows) == 2
    assert rows[0]["project"] == "proj-a"
    assert rows[1]["project"] == "proj-b"


def test_query_runs_empty() -> None:
    conn = _memory_db()
    assert store_mod.query_runs(conn) == []


def _insert_run(conn: sqlite3.Connection, **overrides: Any) -> None:
    defaults: dict[str, Any] = {
        "run_id": "run-1",
        "project": "my-project",
        "task_source": "gh-label",
        "task_description": "fix bug",
        "item_url": "https://github.com/owner/repo/issues/1",
        "trigger_label": "ai-dev",
        "agent": "claude-code",
        "provider": "anthropic",
        "model": "claude-sonnet-4-6",
        "effort": None,
        "started_at": "2024-01-15T10:00:00Z",
        "ended_at": "2024-01-15T10:05:00Z",
        "duration_s": 300.0,
        "outcome": "success",
        "turns_used": 5,
        "total_cost_usd": 0.01,
        "input_tokens": 1000,
        "output_tokens": 500,
        "cache_read_tokens": 200,
        "cache_write_tokens": 100,
        "summary": "Fixed the bug",
        "actions_taken": "[]",
        "failure_reason": None,
        "wip_branch_url": None,
        "chosen_perspective": None,
    }
    defaults.update(overrides)
    cols = ", ".join("?" * len(defaults))
    conn.execute(f"INSERT INTO runs VALUES ({cols})", list(defaults.values()))  # noqa: S608
    conn.commit()


def test_query_runs_limit() -> None:
    conn = _memory_db()
    for i in range(5):
        _insert_run(conn, run_id=f"run-{i}", started_at=f"2024-01-1{i}T10:00:00Z")
    rows = store_mod.query_runs(conn, limit=3)
    assert len(rows) == 3


def test_query_runs_filter_project() -> None:
    conn = _memory_db()
    _insert_run(conn, run_id="run-1", project="proj-a")
    _insert_run(conn, run_id="run-2", project="proj-b")
    rows = store_mod.query_runs(conn, project="proj-a")
    assert len(rows) == 1
    assert rows[0]["project"] == "proj-a"


def test_query_runs_filter_outcome() -> None:
    conn = _memory_db()
    _insert_run(conn, run_id="run-1", outcome="success")
    _insert_run(conn, run_id="run-2", outcome="failure")
    rows = store_mod.query_runs(conn, outcome="failure")
    assert len(rows) == 1
    assert rows[0]["outcome"] == "failure"


def test_query_runs_newest_first() -> None:
    conn = _memory_db()
    _insert_run(conn, run_id="run-old", started_at="2024-01-01T10:00:00Z")
    _insert_run(conn, run_id="run-new", started_at="2024-06-01T10:00:00Z")
    rows = store_mod.query_runs(conn)
    assert rows[0]["started_at"] == "2024-06-01T10:00:00Z"


# ---------------------------------------------------------------------------
# _cmd_review
# ---------------------------------------------------------------------------


def test_review_no_db_exits_0(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    result = _cmd_review(_make_args(db_path=tmp_path / "missing.db"))
    assert result == 0
    assert "No database" in capsys.readouterr().out


def test_review_empty_db_prints_no_runs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "labro.db"
    store_mod.open_db(db).close()
    result = _cmd_review(_make_args(db_path=db))
    assert result == 0
    assert "No runs found" in capsys.readouterr().out


def test_review_shows_rows(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = tmp_path / "labro.db"
    conn = store_mod.open_db(db)
    _insert_run(conn)
    conn.close()
    result = _cmd_review(_make_args(db_path=db))
    assert result == 0
    out = capsys.readouterr().out
    assert "my-project" in out
    assert "success" in out


def test_review_footer_shows_totals(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = tmp_path / "labro.db"
    conn = store_mod.open_db(db)
    _insert_run(conn, run_id="run-1", total_cost_usd=0.01)
    _insert_run(conn, run_id="run-2", total_cost_usd=0.02, started_at="2024-02-01T10:00:00Z")
    conn.close()
    result = _cmd_review(_make_args(db_path=db))
    assert result == 0
    out = capsys.readouterr().out
    assert "2 run(s)" in out
    assert "$0.0300" in out


# ---------------------------------------------------------------------------
# _cmd_list_locks
# ---------------------------------------------------------------------------


def test_list_locks_no_db_exits_0(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    result = _cmd_list_locks(_make_args(db_path=tmp_path / "missing.db"))
    assert result == 0


def test_list_locks_empty_prints_no_locks(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from labro.config.loader import ConfigError

    db = tmp_path / "labro.db"
    store_mod.open_db(db).close()
    with patch("labro.cli.load_config", side_effect=ConfigError("no config")):
        result = _cmd_list_locks(_make_args(db_path=db))
    assert result == 0
    assert "No locks held" in capsys.readouterr().out


def test_list_locks_shows_stale_marker(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = tmp_path / "labro.db"
    conn = store_mod.open_db(db)
    with conn:
        conn.execute(
            "INSERT INTO project_locks VALUES (?, ?)",
            ("my-project", "2020-01-01T00:00:00Z"),
        )
    conn.close()

    config = _make_config()
    with patch("labro.cli.load_config", return_value=config):
        result = _cmd_list_locks(_make_args(db_path=db))
    assert result == 0
    assert "[STALE]" in capsys.readouterr().out


def test_list_locks_shows_project_name(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = tmp_path / "labro.db"
    conn = store_mod.open_db(db)
    with conn:
        conn.execute(
            "INSERT INTO project_locks VALUES (?, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))",
            ("my-project",),
        )
    conn.close()

    config = _make_config()
    with patch("labro.cli.load_config", return_value=config):
        result = _cmd_list_locks(_make_args(db_path=db))
    assert result == 0
    assert "my-project" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# _cmd_unlock
# ---------------------------------------------------------------------------


def test_unlock_no_db_exits_0(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    result = _cmd_unlock(_make_args(db_path=tmp_path / "missing.db", project="my-project"))
    assert result == 0


def test_unlock_existing_lock_prints_held_since(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "labro.db"
    conn = store_mod.open_db(db)
    with conn:
        conn.execute(
            "INSERT INTO project_locks VALUES (?, ?)",
            ("my-project", "2024-01-15T10:00:00Z"),
        )
    conn.close()

    result = _cmd_unlock(_make_args(db_path=db, project="my-project"))
    assert result == 0
    out = capsys.readouterr().out
    assert "Released" in out
    assert "2024-01-15T10:00:00Z" in out


def test_unlock_no_lock_prints_message(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = tmp_path / "labro.db"
    store_mod.open_db(db).close()
    result = _cmd_unlock(_make_args(db_path=db, project="my-project"))
    assert result == 0
    assert "No lock held" in capsys.readouterr().out


def test_unlock_removes_lock(tmp_path: Path) -> None:
    db = tmp_path / "labro.db"
    conn = store_mod.open_db(db)
    with conn:
        conn.execute(
            "INSERT INTO project_locks VALUES (?, ?)",
            ("my-project", "2024-01-15T10:00:00Z"),
        )
    conn.close()

    _cmd_unlock(_make_args(db_path=db, project="my-project"))

    conn2 = store_mod.open_db(db)
    assert store_mod.list_locks(conn2) == []
    conn2.close()
