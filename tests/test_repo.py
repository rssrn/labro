"""Tests for labro.repo — per-run clone, checkout disposal, and dirty-tree reporting.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from labro.repo import (
    clear_tool_caches,
    discard_checkout,
    prepare_repo,
    run_checkout_root,
    summarize_dirty_tree,
    sweep_stale_checkouts,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_completed(stdout: str = "", returncode: int = 0) -> MagicMock:
    """Return a mock CompletedProcess-like object."""
    m = MagicMock()
    m.stdout = stdout
    m.returncode = returncode
    return m


def _age(path: Path, hours: float) -> None:
    """Backdate *path*'s mtime by *hours* so the sweep sees it as stale."""
    ts = time.time() - hours * 3600
    os.utime(path, (ts, ts))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCloneIntoPerRunDir:
    """Every run clones fresh into a directory that did not exist before it started."""

    def test_clones_into_a_run_scoped_dir(self, tmp_path: Path) -> None:
        dest = tmp_path / "run-run-1" / "cli"

        with patch("labro.repo.subprocess.run", side_effect=[_make_completed()]) as mock_run:
            path = prepare_repo("cli/cli", tmp_path, "run-1")

        assert path == dest
        assert path.parent == run_checkout_root(tmp_path, "run-1")
        cmds = [c.args[0] for c in mock_run.call_args_list]
        assert cmds == [["gh", "repo", "clone", "cli/cli", str(dest)]]

    def test_each_run_gets_a_distinct_dir(self, tmp_path: Path) -> None:
        with patch(
            "labro.repo.subprocess.run",
            side_effect=[_make_completed(), _make_completed()],
        ):
            first = prepare_repo("owner/repo", tmp_path, "run-a")
            second = prepare_repo("owner/repo", tmp_path, "run-b")

        assert first != second

    def test_pre_existing_checkouts_are_ignored(self, tmp_path: Path) -> None:
        """No reuse path: an earlier run's copy is never pulled, reset or cleaned."""
        (tmp_path / "repo").mkdir()  # legacy persistent working copy
        (tmp_path / "run-old" / "repo").mkdir(parents=True)  # earlier run's copy

        with patch("labro.repo.subprocess.run", side_effect=[_make_completed()]) as mock_run:
            path = prepare_repo("owner/repo", tmp_path, "run-new")

        assert path == run_checkout_root(tmp_path, "run-new") / "repo"
        cmds = [c.args[0] for c in mock_run.call_args_list]
        assert cmds == [["gh", "repo", "clone", "owner/repo", str(path)]]
        for banned in ("pull", "reset", "clean", "checkout"):
            assert not any(banned in cmd for cmd in cmds), banned


class TestShellFalseEnforced:
    """Every subprocess call must use shell=False."""

    def test_shell_false_enforced_clone(self, tmp_path: Path) -> None:
        with patch("labro.repo.subprocess.run", side_effect=[_make_completed()]) as mock_run:
            prepare_repo("cli/cli", tmp_path, "run-1")

        for c in mock_run.call_args_list:
            assert c.kwargs.get("shell", False) is False, f"shell=True found in call: {c}"


class TestDiscardCheckout:
    """discard_checkout removes the run's whole checkout tree, best-effort."""

    def test_removes_the_run_directory(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run-1"
        (run_dir / "repo" / ".git").mkdir(parents=True)
        (run_dir / "repo" / "app.py").write_text("x")

        discard_checkout(run_dir)

        assert not run_dir.exists()

    def test_missing_directory_is_a_noop(self, tmp_path: Path) -> None:
        discard_checkout(tmp_path / "never-created")  # must not raise

    def test_best_effort_swallows_errors(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        with patch("labro.repo.shutil.rmtree", side_effect=RuntimeError("boom")):
            with caplog.at_level(logging.WARNING, logger="labro.repo"):
                discard_checkout(tmp_path)  # must not raise

        assert any("discard_checkout" in rec.message for rec in caplog.records)


class TestSweepStaleCheckouts:
    """The sweep reclaims orphans without touching live checkouts, and never raises."""

    def test_removes_checkouts_past_the_threshold(self, tmp_path: Path) -> None:
        stale = tmp_path / "run-old"
        (stale / "repo").mkdir(parents=True)
        _age(stale, 24)

        sweep_stale_checkouts(tmp_path)

        assert not stale.exists()

    def test_leaves_a_concurrent_runs_checkout_alone(self, tmp_path: Path) -> None:
        """Projects run concurrently; a young directory belongs to a live run."""
        other = tmp_path / "run-other"
        (other / "repo").mkdir(parents=True)

        sweep_stale_checkouts(tmp_path)

        assert other.exists()

    def test_keep_is_never_removed(self, tmp_path: Path) -> None:
        mine = tmp_path / "run-mine"
        mine.mkdir()
        _age(mine, 999)

        sweep_stale_checkouts(tmp_path, keep=mine)

        assert mine.exists()

    def test_reclaims_legacy_persistent_working_copies(self, tmp_path: Path) -> None:
        """Pre-clean-checkout layout: <repos_dir>/<repo-name>, with no run- prefix."""
        legacy = tmp_path / "labro"
        (legacy / ".git").mkdir(parents=True)
        _age(legacy, 48)

        sweep_stale_checkouts(tmp_path, keep=tmp_path / "run-mine")

        assert not legacy.exists()

    def test_missing_repos_dir_is_a_noop(self, tmp_path: Path) -> None:
        sweep_stale_checkouts(tmp_path / "absent")  # must not raise

    def test_a_failed_delete_never_fails_the_run(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        stale = tmp_path / "run-old"
        stale.mkdir()
        _age(stale, 24)

        with patch("labro.repo.shutil.rmtree", side_effect=OSError("EACCES")):
            with caplog.at_level(logging.WARNING, logger="labro.repo"):
                sweep_stale_checkouts(tmp_path)  # must not raise

        assert any("sweep_stale_checkouts" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------------------
# clear_tool_caches
# ---------------------------------------------------------------------------


class TestClearToolCaches:
    """clear_tool_caches wipes ~/.cache after a run."""

    def test_removes_cache_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_home = tmp_path / "home"
        cache_dir = fake_home / ".cache"
        cache_dir.mkdir(parents=True)
        (cache_dir / "pip-tools").mkdir()
        (cache_dir / "pip-tools" / "http-v2").write_text("stale cache entry")
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        clear_tool_caches()

        assert not cache_dir.exists()

    def test_missing_cache_dir_is_a_noop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        monkeypatch.setattr(Path, "home", lambda: fake_home)

        clear_tool_caches()  # must not raise

        assert not (fake_home / ".cache").exists()

    def test_best_effort_swallows_errors(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        def _boom() -> Path:
            raise RuntimeError("no HOME set")

        monkeypatch.setattr(Path, "home", _boom)

        with caplog.at_level(logging.WARNING, logger="labro.repo"):
            clear_tool_caches()  # must not raise

        assert any("clear_tool_caches" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------------------
# summarize_dirty_tree
# ---------------------------------------------------------------------------


class TestSummarizeDirtyTree:
    """What is left of WIP preservation: report leftovers, never push them."""

    def test_clean_tree_returns_none(self, tmp_path: Path) -> None:
        with patch("labro.repo.subprocess.run", side_effect=[_make_completed(stdout="")]):
            assert summarize_dirty_tree(tmp_path) is None

    def test_dirty_tree_reports_paths_and_shortstat(self, tmp_path: Path) -> None:
        side_effects = [
            _make_completed(stdout=" M src/a.py\n?? src/b.py\n"),  # status --porcelain
            _make_completed(stdout=" 1 file changed, 3 insertions(+)\n"),  # diff --shortstat
        ]

        with patch("labro.repo.subprocess.run", side_effect=side_effects) as mock_run:
            summary = summarize_dirty_tree(tmp_path)

        assert summary == "2 uncommitted path(s); 1 file changed, 3 insertions(+)"
        for c in mock_run.call_args_list:
            assert c.kwargs.get("shell", False) is False, f"shell=True found in call: {c}"

    def test_dirty_tree_without_shortstat_still_reports(self, tmp_path: Path) -> None:
        side_effects = [
            _make_completed(stdout="?? untracked.txt\n"),
            _make_completed(stdout=""),
        ]

        with patch("labro.repo.subprocess.run", side_effect=side_effects):
            assert summarize_dirty_tree(tmp_path) == "1 uncommitted path(s)"

    def test_git_failure_is_swallowed(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        with patch("labro.repo.subprocess.run", side_effect=OSError("git missing")):
            with caplog.at_level(logging.WARNING, logger="labro.repo"):
                assert summarize_dirty_tree(tmp_path) is None

        assert any("summarize_dirty_tree" in rec.message for rec in caplog.records)
