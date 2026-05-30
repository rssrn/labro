"""Repo preparation: clone or update a GitHub repository to a local working copy.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a subprocess with list-form args (shell=False enforced, B602 safe).

    Raises ``subprocess.CalledProcessError`` on non-zero exit.  The stderr
    is logged at ERROR level before raising so that CI logs always show the
    underlying git/gh error without needing to inspect exception attributes.
    """
    result = subprocess.run(
        args,
        shell=False,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "(no output)"
        logger.error(
            "Command failed (exit %d): %s\n%s",
            result.returncode,
            args,
            detail,
        )
        raise subprocess.CalledProcessError(
            result.returncode,
            args,
            output=result.stdout,
            stderr=result.stderr,
        )
    return result


def _get_default_branch(repo: str) -> str:
    """Return the default branch name for the given owner/repo slug."""
    result = _run(
        [
            "gh",
            "repo",
            "view",
            repo,
            "--json",
            "defaultBranchRef",
            "--jq",
            ".defaultBranchRef.name",
        ]
    )
    return result.stdout.strip()


def prepare_repo(repo: str, repos_dir: Path) -> Path:
    """Clone or update a repository and return the path to the working copy.

    Parameters
    ----------
    repo:
        GitHub ``owner/repo`` slug.
    repos_dir:
        Directory under which working copies are stored.  The copy will be
        placed at ``repos_dir/<repo-slug>`` where ``<repo-slug>`` is the
        repository name portion of the slug (everything after the ``/``).

    Returns
    -------
    Path
        Absolute path to the local working copy.

    Notes
    -----
    * All subprocess calls use list-form args with ``shell=False`` (bandit B602
      is never violated).
    * If the working copy is dirty before pulling, a ``git reset --hard``
      and ``git clean -fd`` are performed first so the pull cannot be blocked
      by changes left by a previous run.
    """
    repo_name = repo.split("/", 1)[1]
    dest = repos_dir / repo_name

    default_branch = _get_default_branch(repo)

    if not dest.exists():
        logger.info("Cloning %s into %s", repo, dest)
        _run(["gh", "repo", "clone", repo, str(dest)])
        # After a fresh clone we're already on the default branch; no checkout needed.
    else:
        logger.info("Updating existing working copy at %s", dest)
        _run(["git", "-C", str(dest), "checkout", default_branch])

        # Reset any local changes left by a previous run before pulling,
        # otherwise git pull aborts when tracked files are dirty.
        status_result = subprocess.run(
            ["git", "-C", str(dest), "status", "--porcelain"],
            shell=False,
            check=True,
            capture_output=True,
            text=True,
        )
        dirty_files = status_result.stdout.strip()
        if dirty_files:
            logger.warning(
                "Working copy %s is dirty before pull; resetting. Affected files:\n%s",
                dest,
                dirty_files,
            )
            _run(["git", "-C", str(dest), "reset", "--hard"])
            _run(["git", "-C", str(dest), "clean", "-fd"])

        # Pass gh as the credential helper so GH_TOKEN is used for HTTPS auth.
        # git pull doesn't inherit gh's auth automatically — only gh subcommands do.
        _run(
            [
                "git",
                "-C",
                str(dest),
                "-c",
                "credential.helper=!gh auth git-credential",
                "pull",
            ]
        )

    return dest


def _gh_user_identity() -> tuple[str, str]:
    """Return (name, email) for the authenticated gh user.

    Email uses GitHub's noreply address so private emails are never exposed.
    Falls back to ("Labro", "labro@users.noreply.github.com") if the gh call fails.
    """
    try:
        result = subprocess.run(
            ["gh", "api", "user", "--jq", '[.login, .id] | join(" ")'],
            shell=False,
            check=True,
            capture_output=True,
            text=True,
        )
        parts = result.stdout.strip().split()
        login = parts[0]
        uid = parts[1] if len(parts) > 1 else ""
        email = (
            f"{uid}+{login}@users.noreply.github.com"
            if uid
            else f"{login}@users.noreply.github.com"
        )
        return login, email
    except Exception:
        return "Labro", "labro@users.noreply.github.com"


def preserve_wip(repo_path: Path, repo: str, run_id: str) -> str | None:
    """Push any dirty working copy to a ``labro-wip/<run-id>`` branch.

    Best-effort — never raises. Returns the branch web URL on success, or
    ``None`` if the copy is clean or if any git/push step fails.

    @author Claude Sonnet 4.6 Anthropic
    """
    try:
        status_result = subprocess.run(
            ["git", "-C", str(repo_path), "status", "--porcelain"],
            shell=False,
            check=True,
            capture_output=True,
            text=True,
        )
        if not status_result.stdout.strip():
            return None

        git_name, git_email = _gh_user_identity()
        branch = f"labro-wip/{run_id}"
        _run(["git", "-C", str(repo_path), "checkout", "-b", branch])
        _run(["git", "-C", str(repo_path), "add", "-A"])
        _run(
            [
                "git",
                "-C",
                str(repo_path),
                "-c",
                f"user.name={git_name}",
                "-c",
                f"user.email={git_email}",
                "commit",
                "-m",
                f"WIP: labro run {run_id}",
            ]
        )
        _run(
            [
                "git",
                "-C",
                str(repo_path),
                "-c",
                "credential.helper=!gh auth git-credential",
                "push",
                "--set-upstream",
                "origin",
                branch,
            ]
        )
        return f"https://github.com/{repo}/tree/{branch}"
    except Exception:
        logger.warning("preserve_wip failed for run %s", run_id, exc_info=True)
        return None
