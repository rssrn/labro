"""Tests for labro.repo — per-run clone, checkout disposal, and WIP preservation.

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
    preserve_wip,
    run_checkout_root,
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
            path, wip = prepare_repo("cli/cli", tmp_path, "run-1")

        assert path == dest
        assert wip is None
        assert path.parent == run_checkout_root(tmp_path, "run-1")
        cmds = [c.args[0] for c in mock_run.call_args_list]
        assert cmds == [["gh", "repo", "clone", "cli/cli", str(dest)]]

    def test_each_run_gets_a_distinct_dir(self, tmp_path: Path) -> None:
        with patch(
            "labro.repo.subprocess.run",
            side_effect=[_make_completed(), _make_completed()],
        ):
            first, _ = prepare_repo("owner/repo", tmp_path, "run-a")
            second, _ = prepare_repo("owner/repo", tmp_path, "run-b")

        assert first != second

    def test_pre_existing_checkouts_are_ignored(self, tmp_path: Path) -> None:
        """No reuse path: an earlier run's copy is never pulled, reset or cleaned."""
        (tmp_path / "repo").mkdir()  # legacy persistent working copy
        (tmp_path / "run-old" / "repo").mkdir(parents=True)  # earlier run's copy

        with patch("labro.repo.subprocess.run", side_effect=[_make_completed()]) as mock_run:
            path, _ = prepare_repo("owner/repo", tmp_path, "run-new")

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

    def test_shell_false_enforced_wip_resume(self, tmp_path: Path) -> None:
        side_effects = [
            _make_completed(),  # clone
            _make_completed(stdout="refs/heads/labro-wip/x\n"),  # ls-remote
            _make_completed(),  # fetch
            _make_completed(),  # checkout -B
        ]

        with patch("labro.repo.subprocess.run", side_effect=side_effects) as mock_run:
            prepare_repo("cli/cli", tmp_path, "run-1", wip_branch="labro-wip/x")

        for c in mock_run.call_args_list:
            assert c.kwargs.get("shell", False) is False, f"shell=True found in call: {c}"


# ---------------------------------------------------------------------------
# preserve_wip
# ---------------------------------------------------------------------------


class TestPreserveWip:
    """Unit tests for preserve_wip — WIP branch creation and push."""

    def test_clean_repo_returns_none(self, tmp_path: Path) -> None:
        """Clean working copy → return None without running any git commands."""
        with patch("labro.repo.subprocess.run") as mock_run:
            mock_run.return_value = _make_completed(stdout="")  # clean
            result = preserve_wip(tmp_path, "owner/repo", "run-123")

        assert result is None
        # Only git status should have been called
        called_cmds = [c.args[0] for c in mock_run.call_args_list]
        assert len(called_cmds) == 1
        assert "status" in called_cmds[0]

    def test_dirty_repo_creates_branch_and_pushes(self, tmp_path: Path) -> None:
        """Dirty working copy → branch/add/commit/push sequence; returns URL."""
        dirty_output = " M some_file.py"
        side_effects = [
            _make_completed(stdout=dirty_output),  # git status
            _make_completed(stdout="main\n"),  # git rev-parse --abbrev-ref HEAD
            _make_completed(stdout="mylogin 12345678\n"),  # gh api user (identity)
            _make_completed(),  # git checkout -b
            _make_completed(),  # git add -A
            _make_completed(),  # git commit
            _make_completed(),  # git push
        ]

        with patch("labro.repo.subprocess.run", side_effect=side_effects) as mock_run:
            url = preserve_wip(tmp_path, "owner/repo", "run-abc")

        assert url == "https://github.com/owner/repo/tree/labro-wip/run-abc"
        cmds = [c.args[0] for c in mock_run.call_args_list]
        assert any("checkout" in cmd and "labro-wip/run-abc" in cmd for cmd in cmds)
        assert any("add" in cmd for cmd in cmds)
        assert any("commit" in cmd for cmd in cmds)
        assert any("push" in cmd for cmd in cmds)

    def test_push_failure_returns_none_and_warns(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """If push fails, return None (best-effort) and log a warning."""
        import subprocess

        dirty_output = " M some_file.py"
        side_effects = [
            _make_completed(stdout=dirty_output),  # git status
            _make_completed(stdout="main\n"),  # git rev-parse --abbrev-ref HEAD
            _make_completed(stdout="mylogin 12345678\n"),  # gh api user (identity)
            _make_completed(),  # git checkout -b
            _make_completed(),  # git add -A
            _make_completed(),  # git commit
            MagicMock(returncode=1, stdout="", stderr="push denied"),  # git push (fails)
        ]

        def fake_run(args: list[str], **kwargs: object) -> MagicMock:
            effect = side_effects.pop(0)
            if isinstance(effect, MagicMock) and effect.returncode != 0:
                raise subprocess.CalledProcessError(1, args, stderr="push denied")
            return effect

        with patch("labro.repo.subprocess.run", side_effect=fake_run):
            with caplog.at_level(logging.WARNING, logger="labro.repo"):
                result = preserve_wip(tmp_path, "owner/repo", "run-fail")

        assert result is None
        assert any("preserve_wip" in rec.message for rec in caplog.records)

    def test_shell_false_enforced(self, tmp_path: Path) -> None:
        """All subprocess calls in preserve_wip must use shell=False."""
        dirty_output = " M x.py"
        side_effects = [
            _make_completed(stdout=dirty_output),  # git status
            _make_completed(stdout="main\n"),  # git rev-parse --abbrev-ref HEAD
            _make_completed(stdout="mylogin 12345678\n"),  # gh api user (identity)
            _make_completed(),  # git checkout -b
            _make_completed(),  # git add -A
            _make_completed(),  # git commit
            _make_completed(),  # git push
        ]

        with patch("labro.repo.subprocess.run", side_effect=side_effects) as mock_run:
            preserve_wip(tmp_path, "owner/repo", "run-shell-check")

        for c in mock_run.call_args_list:
            assert c.kwargs.get("shell", False) is False, f"shell=True in: {c}"

    def test_bot_identity_skips_gh_api_call(self, tmp_path: Path) -> None:
        """When bot_identity is provided, no gh api user call is made."""
        dirty_output = " M some_file.py"
        side_effects = [
            _make_completed(stdout=dirty_output),  # git status
            _make_completed(stdout="main\n"),  # git rev-parse --abbrev-ref HEAD
            # no gh api user call — identity supplied directly
            _make_completed(),  # git checkout -b
            _make_completed(),  # git add -A
            _make_completed(),  # git commit
            _make_completed(),  # git push
        ]

        with patch("labro.repo.subprocess.run", side_effect=side_effects) as mock_run:
            url = preserve_wip(
                tmp_path,
                "owner/repo",
                "run-bot",
                bot_identity=(
                    "labro-rssrn[bot]",
                    "12345+labro-rssrn[bot]@users.noreply.github.com",
                ),
            )

        assert url == "https://github.com/owner/repo/tree/labro-wip/run-bot"
        cmds = [c.args[0] for c in mock_run.call_args_list]
        gh_calls = [cmd for cmd in cmds if cmd[0] == "gh"]
        assert not gh_calls, f"no gh calls expected when bot_identity is provided, got: {gh_calls}"
        # Verify bot identity appears in the commit command
        commit_call = next(c for c in mock_run.call_args_list if "commit" in c.args[0])
        commit_args_flat = " ".join(commit_call.args[0])
        assert "labro-rssrn[bot]" in commit_args_flat
        assert "12345+labro-rssrn[bot]@users.noreply.github.com" in commit_args_flat

    def test_already_on_wip_branch_reuses_it(self, tmp_path: Path) -> None:
        """If already on a labro-wip/* branch, no new branch is created — commits to existing."""
        dirty_output = " M some_file.py"
        side_effects = [
            _make_completed(stdout=dirty_output),  # git status
            _make_completed(stdout="labro-wip/prior-run-id\n"),  # git rev-parse (on WIP branch)
            _make_completed(stdout="mylogin 12345678\n"),  # gh api user (identity)
            # No checkout -b — already on branch
            _make_completed(),  # git add -A
            _make_completed(),  # git commit
            _make_completed(),  # git push
        ]

        with patch("labro.repo.subprocess.run", side_effect=side_effects) as mock_run:
            url = preserve_wip(tmp_path, "owner/repo", "new-run-id")

        assert url == "https://github.com/owner/repo/tree/labro-wip/prior-run-id"
        cmds = [c.args[0] for c in mock_run.call_args_list]
        assert not any("checkout" in cmd for cmd in cmds), "should not create new branch"
        assert any("add" in cmd for cmd in cmds)
        assert any("commit" in cmd for cmd in cmds)
        assert any("push" in cmd for cmd in cmds)


# ---------------------------------------------------------------------------
# discard_checkout / sweep_stale_checkouts
# ---------------------------------------------------------------------------


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
# prepare_repo — WIP branch checkout
# ---------------------------------------------------------------------------


class TestWipBranchCheckout:
    """prepare_repo checks out a WIP branch when wip_branch is given and exists on remote."""

    def test_wip_branch_found_and_checked_out(self, tmp_path: Path) -> None:
        """WIP branch exists on remote -> fetch + checkout -B; returns (path, branch)."""
        dest = run_checkout_root(tmp_path, "run-1") / "repo"
        wip = "labro-wip/prior-run-id"

        side_effects = [
            _make_completed(),  # clone
            _make_completed(stdout="refs/heads/labro-wip/prior-run-id\n"),  # ls-remote
            _make_completed(),  # fetch
            _make_completed(),  # checkout -B
        ]

        with patch("labro.repo.subprocess.run", side_effect=side_effects) as mock_run:
            path, checked_out = prepare_repo("owner/repo", tmp_path, "run-1", wip_branch=wip)

        assert path == dest
        assert checked_out == wip

        # ls-remote and fetch must both use the credential helper
        cmds = [c.args[0] for c in mock_run.call_args_list]
        ls_remote_cmd = next(cmd for cmd in cmds if "ls-remote" in cmd)
        fetch_cmd = next(cmd for cmd in cmds if "fetch" in cmd)
        assert "credential.helper=!gh auth git-credential" in ls_remote_cmd
        assert "credential.helper=!gh auth git-credential" in fetch_cmd

    def test_wip_branch_not_found_falls_back(self, tmp_path: Path) -> None:
        """WIP branch absent on remote -> returns (path, None)."""
        wip = "labro-wip/stale-run-id"

        side_effects = [
            _make_completed(),  # clone
            _make_completed(returncode=2),  # ls-remote — branch not found
        ]

        with patch("labro.repo.subprocess.run", side_effect=side_effects):
            path, checked_out = prepare_repo("owner/repo", tmp_path, "run-1", wip_branch=wip)

        assert path == run_checkout_root(tmp_path, "run-1") / "repo"
        assert checked_out is None

    def test_no_wip_branch_returns_none(self, tmp_path: Path) -> None:
        """When wip_branch is not specified, second return value is always None."""
        with patch("labro.repo.subprocess.run", side_effect=[_make_completed()]):
            path, checked_out = prepare_repo("owner/repo", tmp_path, "run-1")

        assert path == run_checkout_root(tmp_path, "run-1") / "repo"
        assert checked_out is None
