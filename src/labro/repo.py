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
    * If the working copy is dirty after checkout/pull, a ``git reset --hard``
      and ``git clean -fd`` are performed automatically and a warning is logged.
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

    # Dirty-repo check
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
            "Working copy %s is dirty; resetting. Affected files:\n%s",
            dest,
            dirty_files,
        )
        _run(["git", "-C", str(dest), "reset", "--hard"])
        _run(["git", "-C", str(dest), "clean", "-fd"])

    return dest
