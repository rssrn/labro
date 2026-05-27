"""Tests for labro.repo — clone/pull/dirty-recovery logic.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from labro.repo import prepare_repo

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

        # gh repo view → default branch; gh repo clone; git status --porcelain (clean)
        side_effects = [
            _make_completed(stdout="main\n"),  # gh repo view
            _make_completed(),  # gh repo clone
            _make_completed(stdout=""),  # git status --porcelain (clean)
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
        # Third call: git status
        assert calls[2].args[0] == ["git", "-C", str(dest), "status", "--porcelain"]

        # No checkout or pull
        all_cmds = [c.args[0] for c in calls]
        assert not any("checkout" in cmd for cmd in all_cmds)
        assert not any("pull" in cmd for cmd in all_cmds)


class TestPullWhenPresent:
    """When the destination directory already exists, checkout + pull are run."""

    def test_pull_when_present(self, tmp_path: Path) -> None:
        dest = tmp_path / "cli"
        dest.mkdir()  # directory EXISTS

        side_effects = [
            _make_completed(stdout="main\n"),  # gh repo view
            _make_completed(),  # git checkout main
            _make_completed(),  # git pull
            _make_completed(stdout=""),  # git status --porcelain (clean)
        ]

        with patch("labro.repo.subprocess.run", side_effect=side_effects) as mock_run:
            result = prepare_repo("cli/cli", tmp_path)

        assert result == dest

        calls = mock_run.call_args_list
        cmds = [c.args[0] for c in calls]

        assert ["git", "-C", str(dest), "checkout", "main"] in cmds
        assert ["git", "-C", str(dest), "pull"] in cmds
        # No clone
        assert not any("clone" in cmd for cmd in cmds)

    def test_no_clone_when_present(self, tmp_path: Path) -> None:
        dest = tmp_path / "myrepo"
        dest.mkdir()

        side_effects = [
            _make_completed(stdout="develop\n"),
            _make_completed(),  # checkout
            _make_completed(),  # pull
            _make_completed(stdout=""),
        ]

        with patch("labro.repo.subprocess.run", side_effect=side_effects) as mock_run:
            prepare_repo("owner/myrepo", tmp_path)

        cmds = [c.args[0] for c in mock_run.call_args_list]
        assert not any("clone" in cmd for cmd in cmds)


class TestDirtyRepoTriggersRecovery:
    """If `git status --porcelain` returns output, reset + clean are called."""

    def test_dirty_repo_triggers_recovery(self, tmp_path: Path) -> None:
        dest = tmp_path / "myrepo"
        dest.mkdir()

        dirty_output = " M src/foo.py\n?? untracked.txt"
        side_effects = [
            _make_completed(stdout="main\n"),  # gh repo view
            _make_completed(),  # git checkout
            _make_completed(),  # git pull
            _make_completed(stdout=dirty_output),  # git status --porcelain (DIRTY)
            _make_completed(),  # git reset --hard
            _make_completed(),  # git clean -fd
        ]

        with patch("labro.repo.subprocess.run", side_effect=side_effects) as mock_run:
            prepare_repo("owner/myrepo", tmp_path)

        cmds = [c.args[0] for c in mock_run.call_args_list]
        assert ["git", "-C", str(dest), "reset", "--hard"] in cmds
        assert ["git", "-C", str(dest), "clean", "-fd"] in cmds

    def test_warning_logged_when_dirty(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        dest = tmp_path / "repo"
        dest.mkdir()

        side_effects = [
            _make_completed(stdout="main\n"),
            _make_completed(),
            _make_completed(),
            _make_completed(stdout=" M dirty.py"),
            _make_completed(),
            _make_completed(),
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
            _make_completed(),  # pull
            _make_completed(stdout=""),  # clean status
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
            _make_completed(stdout=""),
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
            _make_completed(),
            _make_completed(),
            _make_completed(stdout=""),
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
            _make_completed(),
            _make_completed(),
            _make_completed(stdout=" M dirty.py"),
            _make_completed(),
            _make_completed(),
        ]

        with patch("labro.repo.subprocess.run", side_effect=side_effects) as mock_run:
            prepare_repo("owner/repo", tmp_path)

        for c in mock_run.call_args_list:
            assert c.kwargs.get("shell", False) is False, f"shell=True found in call: {c}"
