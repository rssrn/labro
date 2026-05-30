"""Tests for labro.repo — clone/pull/dirty-recovery logic.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from labro.repo import prepare_repo, preserve_wip

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_completed(stdout: str = "", returncode: int = 0) -> MagicMock:
    """Return a mock CompletedProcess-like object."""
    m = MagicMock()
    m.stdout = stdout
    m.returncode = returncode
    return m


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCloneWhenAbsent:
    """When the destination directory does not exist, the repo is cloned."""

    def test_clone_when_absent(self, tmp_path: Path) -> None:
        dest = tmp_path / "cli"  # does NOT exist yet

        # gh repo view → default branch; gh repo clone (no status check on fresh clone)
        side_effects = [
            _make_completed(stdout="main\n"),  # gh repo view
            _make_completed(),  # gh repo clone
        ]

        with patch("labro.repo.subprocess.run", side_effect=side_effects) as mock_run:
            result = prepare_repo("cli/cli", tmp_path)

        assert result == dest

        calls = mock_run.call_args_list
        # First call: gh repo view
        assert calls[0].args[0] == [
            "gh",
            "repo",
            "view",
            "cli/cli",
            "--json",
            "defaultBranchRef",
            "--jq",
            ".defaultBranchRef.name",
        ]
        # Second call: gh repo clone
        assert calls[1].args[0] == ["gh", "repo", "clone", "cli/cli", str(dest)]

        # No checkout or pull
        all_cmds = [c.args[0] for c in calls]
        assert not any("checkout" in cmd for cmd in all_cmds)
        assert not any("pull" in cmd for cmd in all_cmds)


class TestPullWhenPresent:
    """When the destination directory already exists, checkout + pull are run."""

    def test_pull_when_present(self, tmp_path: Path) -> None:
        dest = tmp_path / "cli"
        dest.mkdir()  # directory EXISTS

        # Status check now happens BEFORE pull so dirty repos can be reset first.
        side_effects = [
            _make_completed(stdout="main\n"),  # gh repo view
            _make_completed(),  # git checkout main
            _make_completed(stdout=""),  # git status --porcelain (clean)
            _make_completed(),  # git pull
        ]

        with patch("labro.repo.subprocess.run", side_effect=side_effects) as mock_run:
            result = prepare_repo("cli/cli", tmp_path)

        assert result == dest

        calls = mock_run.call_args_list
        cmds = [c.args[0] for c in calls]

        assert ["git", "-C", str(dest), "checkout", "main"] in cmds
        assert [
            "git",
            "-C",
            str(dest),
            "-c",
            "credential.helper=!gh auth git-credential",
            "pull",
        ] in cmds
        # No clone
        assert not any("clone" in cmd for cmd in cmds)

    def test_no_clone_when_present(self, tmp_path: Path) -> None:
        dest = tmp_path / "myrepo"
        dest.mkdir()

        side_effects = [
            _make_completed(stdout="develop\n"),
            _make_completed(),  # checkout
            _make_completed(stdout=""),  # status (clean)
            _make_completed(),  # pull
        ]

        with patch("labro.repo.subprocess.run", side_effect=side_effects) as mock_run:
            prepare_repo("owner/myrepo", tmp_path)

        cmds = [c.args[0] for c in mock_run.call_args_list]
        assert not any("clone" in cmd for cmd in cmds)


class TestDirtyRepoTriggersRecovery:
    """If `git status --porcelain` returns output, reset + clean are called before pull."""

    def test_dirty_repo_triggers_recovery(self, tmp_path: Path) -> None:
        dest = tmp_path / "myrepo"
        dest.mkdir()

        dirty_output = " M src/foo.py\n?? untracked.txt"
        side_effects = [
            _make_completed(stdout="main\n"),  # gh repo view
            _make_completed(),  # git checkout
            _make_completed(stdout=dirty_output),  # git status --porcelain (DIRTY)
            _make_completed(),  # git reset --hard
            _make_completed(),  # git clean -fd
            _make_completed(),  # git pull
        ]

        with patch("labro.repo.subprocess.run", side_effect=side_effects) as mock_run:
            prepare_repo("owner/myrepo", tmp_path)

        cmds = [c.args[0] for c in mock_run.call_args_list]
        assert ["git", "-C", str(dest), "reset", "--hard"] in cmds
        assert ["git", "-C", str(dest), "clean", "-fd"] in cmds
        # Pull must still run after the reset
        assert any("pull" in cmd for cmd in cmds), "git pull should run after dirty-repo recovery"

    def test_warning_logged_when_dirty(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        dest = tmp_path / "repo"
        dest.mkdir()

        side_effects = [
            _make_completed(stdout="main\n"),
            _make_completed(),  # checkout
            _make_completed(stdout=" M dirty.py"),  # status (dirty)
            _make_completed(),  # reset
            _make_completed(),  # clean
            _make_completed(),  # pull
        ]

        with patch("labro.repo.subprocess.run", side_effect=side_effects):
            with caplog.at_level(logging.WARNING, logger="labro.repo"):
                prepare_repo("owner/repo", tmp_path)

        assert any("dirty" in record.message.lower() for record in caplog.records)


class TestCleanRepoNoRecovery:
    """`git status --porcelain` returns empty → no reset/clean calls."""

    def test_clean_repo_no_recovery(self, tmp_path: Path) -> None:
        dest = tmp_path / "myrepo"
        dest.mkdir()

        side_effects = [
            _make_completed(stdout="main\n"),
            _make_completed(),  # checkout
            _make_completed(stdout=""),  # status (clean)
            _make_completed(),  # pull
        ]

        with patch("labro.repo.subprocess.run", side_effect=side_effects) as mock_run:
            prepare_repo("owner/myrepo", tmp_path)

        cmds = [c.args[0] for c in mock_run.call_args_list]
        assert not any("reset" in cmd for cmd in cmds)
        assert not any("clean" in cmd for cmd in cmds)


class TestShellFalseEnforced:
    """Every subprocess call must use shell=False."""

    def test_shell_false_enforced_absent(self, tmp_path: Path) -> None:
        """Clone path: no shell=True allowed."""
        side_effects = [
            _make_completed(stdout="main\n"),
            _make_completed(),
        ]

        with patch("labro.repo.subprocess.run", side_effect=side_effects) as mock_run:
            prepare_repo("cli/cli", tmp_path)

        for c in mock_run.call_args_list:
            assert c.kwargs.get("shell", False) is False, f"shell=True found in call: {c}"

    def test_shell_false_enforced_present(self, tmp_path: Path) -> None:
        """Update path: no shell=True allowed."""
        dest = tmp_path / "cli"
        dest.mkdir()

        side_effects = [
            _make_completed(stdout="main\n"),
            _make_completed(),  # checkout
            _make_completed(stdout=""),  # status (clean)
            _make_completed(),  # pull
        ]

        with patch("labro.repo.subprocess.run", side_effect=side_effects) as mock_run:
            prepare_repo("cli/cli", tmp_path)

        for c in mock_run.call_args_list:
            assert c.kwargs.get("shell", False) is False, f"shell=True found in call: {c}"

    def test_shell_false_enforced_dirty(self, tmp_path: Path) -> None:
        """Dirty-recovery path: no shell=True allowed."""
        dest = tmp_path / "repo"
        dest.mkdir()

        side_effects = [
            _make_completed(stdout="main\n"),
            _make_completed(),  # checkout
            _make_completed(stdout=" M dirty.py"),  # status (dirty)
            _make_completed(),  # reset
            _make_completed(),  # clean
            _make_completed(),  # pull
        ]

        with patch("labro.repo.subprocess.run", side_effect=side_effects) as mock_run:
            prepare_repo("owner/repo", tmp_path)

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
