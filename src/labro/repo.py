"""Repo preparation: clone a GitHub repository into a fresh per-run working copy.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import time
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


# Prefix for the per-run directory holding one run's working copy.
_RUN_DIR_PREFIX = "run-"

# How long a per-run checkout may sit before ``sweep_stale_checkouts`` reclaims
# it. Every agent attempt is bounded by ``timeout_s`` (900s at the longest in
# production) and a run tries at most a handful of fallback tiers, so six hours
# is far beyond any live run — the sweep cannot race a concurrently-running
# project's checkout. Do not relax this to days: the only checkouts that reach
# the sweep are those a SIGKILL'd or OOM'd run failed to delete, and they still
# carry whatever ``.venv`` / ``node_modules`` the agent built (hundreds of MB
# for a frontend repo), so the window is also the disk-leak window.
_STALE_CHECKOUT_S = 6 * 60 * 60


def run_checkout_root(repos_dir: Path, run_id: str) -> Path:
    """Return the per-run directory that holds *run_id*'s working copy.

    One directory per run, so the sweep and the end-of-run delete both operate
    on a single path regardless of how many repos a run touched.

    @author Claude Opus 5 Anthropic
    """
    return repos_dir / f"{_RUN_DIR_PREFIX}{run_id}"


def prepare_repo(
    repo: str, repos_dir: Path, run_id: str, wip_branch: str | None = None
) -> tuple[Path, str | None]:
    """Clone a repository into a fresh per-run directory and return its path.

    Parameters
    ----------
    repo:
        GitHub ``owner/repo`` slug.
    repos_dir:
        Directory under which per-run working copies are stored.  The copy is
        placed at ``repos_dir/run-<run_id>/<repo-name>``.
    run_id:
        The current run's id, which scopes the checkout to this run.
    wip_branch:
        If provided, try to check out this branch (e.g. ``labro-wip/<run-id>``)
        after cloning.  The second return value reports whether the checkout
        succeeded.

    Returns
    -------
    tuple[Path, str | None]
        ``(repo_path, checked_out_wip)`` where ``checked_out_wip`` is the WIP
        branch name if it was successfully checked out, else ``None``.

    Notes
    -----
    * The clone target did not exist before this call, so no git state written
      by a previous run — dirty tree, diverged local branch, ``.git/config``
      residue, stashes, hooks — can be observed by this one.  Agents have full
      shell access inside the checkout, so the set of states they can leave
      behind is unbounded; the only reliable defence is not to reuse it.
    * The clone is full, not ``--depth 1``: agents genuinely read history
      (dependency-pin archaeology, several of the perspectives in
      ``perspectives.toml``), and a shallow clone would degrade that silently.
    * The caller is responsible for deleting ``run_checkout_root(...)`` when the
      run ends — see ``discard_checkout``.
    * All subprocess calls use list-form args with ``shell=False`` (bandit B602
      is never violated).

    @author Claude Opus 5 Anthropic
    """
    repo_name = repo.split("/", 1)[1]
    dest = run_checkout_root(repos_dir, run_id) / repo_name

    dest.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Cloning %s into %s", repo, dest)
    _run(["gh", "repo", "clone", repo, str(dest)])
    # A fresh clone lands on the default branch; no checkout needed.

    if wip_branch is not None:
        # Credential helper required — git ls-remote doesn't inherit gh auth automatically.
        # Exit code 2 means "no matching refs"; other non-zero codes mean auth/network error.
        ls_result = subprocess.run(
            [
                "git",
                "-C",
                str(dest),
                "-c",
                "credential.helper=!gh auth git-credential",
                "ls-remote",
                "--exit-code",
                "origin",
                wip_branch,
            ],
            shell=False,
            check=False,
            capture_output=True,
            text=True,
        )
        if ls_result.returncode == 0:
            logger.info("Checking out WIP branch %s for resume", wip_branch)
            _run(
                [
                    "git",
                    "-C",
                    str(dest),
                    "-c",
                    "credential.helper=!gh auth git-credential",
                    "fetch",
                    "origin",
                    wip_branch,
                ]
            )
            # -B creates the local branch if absent, or resets it to the remote ref.
            _run(
                [
                    "git",
                    "-C",
                    str(dest),
                    "checkout",
                    "-B",
                    wip_branch,
                    f"origin/{wip_branch}",
                ]
            )
            return dest, wip_branch
        if ls_result.returncode == 2:
            logger.warning(
                "WIP branch %s not found on remote; starting from the default branch",
                wip_branch,
            )
        else:
            logger.warning(
                "ls-remote failed (exit %d) checking for WIP branch %s;"
                " starting from the default branch\n%s",
                ls_result.returncode,
                wip_branch,
                ls_result.stderr.strip(),
            )

    return dest, None


def discard_checkout(run_dir: Path) -> None:
    """Delete a run's per-run checkout directory.

    Best-effort — never raises, and a missing directory is not an error (most
    runs skip at the picker and never clone anything).  Called from the run
    loop's ``finally`` *after* the process reaper, so a stray agent process
    cannot still be writing inside the tree while it is being removed.

    @author Claude Opus 5 Anthropic
    """
    try:
        shutil.rmtree(run_dir, ignore_errors=True)
    except Exception:
        logger.warning("discard_checkout failed for %s", run_dir, exc_info=True)


def sweep_stale_checkouts(repos_dir: Path, *, keep: Path | None = None) -> None:
    """Reclaim checkout directories left behind by runs that never cleaned up.

    Best-effort — never raises.  This runs on *every* run, including the ~97%
    that skip at the picker, so an unreadable leftover or a delete race must
    never turn into a run failure.

    Anything under *repos_dir* older than ``_STALE_CHECKOUT_S`` is removed,
    except *keep* (this run's own directory).  The age threshold, not an
    ownership test, is what makes this safe: runs for different projects
    execute concurrently and each holds its own ``run-<id>`` directory, so a
    "delete everything that isn't mine" sweep would destroy a live checkout.

    The rule is deliberately not restricted to ``run-`` prefixed directories:
    it also reclaims the persistent per-repo working copies left over from the
    pre-clean-checkout layout (``<repos_dir>/<repo-name>``), which nothing
    reads any more.

    @author Claude Opus 5 Anthropic
    """
    try:
        entries = sorted(repos_dir.iterdir())
    except FileNotFoundError:
        return  # repos_dir absent on a first run — nothing to sweep.
    except Exception:
        logger.warning("sweep_stale_checkouts could not list %s", repos_dir, exc_info=True)
        return

    now = time.time()
    for entry in entries:
        try:
            if keep is not None and entry == keep:
                continue
            if not entry.is_dir():
                continue
            age_s = now - entry.stat().st_mtime
            if age_s < _STALE_CHECKOUT_S:
                continue
            logger.info(
                "Sweeping stale checkout %s (age %.1fh)",
                entry,
                age_s / 3600,
            )
            shutil.rmtree(entry, ignore_errors=True)
        except Exception:
            logger.warning("sweep_stale_checkouts failed for %s", entry, exc_info=True)


def clear_tool_caches() -> None:
    """Wipe ``~/.cache`` inside the container after a run.

    Best-effort — never raises. Package-manager tools invoked by the agent
    (``pip``, ``pip-tools``, ``uv``, ...) cache HTTP responses and build
    artifacts under ``~/.cache`` by XDG convention. Because the container
    itself is long-lived (not recreated between runs), this directory sits
    outside both the per-repo working copy (unaffected by
    ``cleanup_working_copy``) and the ``/data`` bind mount, and grows
    unbounded in the container's own writable layer otherwise — e.g. a
    single dependency resolution against a large package can leave several
    GB behind. Auth/config state for the CLIs Labro shells out to (``gh``,
    ``codex``, ``claude``, ``npm``) lives elsewhere (``~/.config``,
    ``~/.codex``, ``~/.npm``), not under ``~/.cache``, so this is safe to
    clear unconditionally. Losing the cache costs a cold re-resolve on the
    next run that touches the same dependencies — an acceptable trade given
    how rarely Labro re-resolves the same repo's deps back-to-back.

    @author Claude Sonnet 4.6 Anthropic
    """
    try:
        shutil.rmtree(Path.home() / ".cache", ignore_errors=True)
    except Exception:
        logger.warning("clear_tool_caches failed", exc_info=True)


def _gh_user_identity(
    bot_identity: tuple[str, str] | None = None,
) -> tuple[str, str]:
    """Return (name, email) for commit authorship.

    If *bot_identity* is provided (GitHub App mode), it is returned directly.
    Otherwise queries ``gh api user`` and falls back to a generic identity on
    any error.
    """
    if bot_identity is not None:
        return bot_identity
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


def preserve_wip(
    repo_path: Path,
    repo: str,
    run_id: str,
    *,
    bot_identity: tuple[str, str] | None = None,
) -> str | None:
    """Push any dirty working copy to a ``labro-wip/<run-id>`` branch.

    Best-effort — never raises. Returns the branch web URL on success, or
    ``None`` if the copy is clean or if any git/push step fails.

    Pass *bot_identity* as ``(name, email)`` when using GitHub App auth to
    override the default ``gh api user`` identity lookup.

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

        # Reuse the current branch if already on a WIP branch. Since checkouts are
        # cloned fresh per run, the only way HEAD sits on ``labro-wip/*`` is the
        # resume path in ``prepare_repo`` — a resumed run that fails again keeps
        # appending to the same branch rather than forking a new one.
        current_result = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "--abbrev-ref", "HEAD"],
            shell=False,
            check=True,
            capture_output=True,
            text=True,
        )
        current_branch = current_result.stdout.strip()

        git_name, git_email = _gh_user_identity(bot_identity)

        if current_branch.startswith("labro-wip/"):
            branch = current_branch
        else:
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
