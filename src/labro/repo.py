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


def prepare_repo(repo: str, repos_dir: Path, run_id: str) -> Path:
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

    Returns
    -------
    Path
        The path of the cloned working copy.

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
    return dest


def summarize_dirty_tree(repo_path: Path) -> str | None:
    """Return a one-line description of uncommitted changes, or ``None`` if clean.

    Best-effort — never raises; an unreadable or missing checkout is reported as
    clean.  This is all that remains of WIP-branch preservation (removed in #62):
    the harness no longer pushes an agent's leftovers anywhere, but a run that
    ends badly still records whether the agent had real work in the tree when it
    was discarded, which is the only question the WIP branches ever answered.

    @author Claude Opus 5 Anthropic
    """
    try:
        status = subprocess.run(
            ["git", "-C", str(repo_path), "status", "--porcelain"],
            shell=False,
            check=True,
            capture_output=True,
            text=True,
        )
        entries = [line for line in status.stdout.splitlines() if line.strip()]
        if not entries:
            return None
        shortstat = subprocess.run(
            ["git", "-C", str(repo_path), "diff", "--shortstat", "HEAD"],
            shell=False,
            check=False,
            capture_output=True,
            text=True,
        )
        detail = shortstat.stdout.strip()
        summary = f"{len(entries)} uncommitted path(s)"
        return f"{summary}; {detail}" if detail else summary
    except Exception:
        logger.warning("summarize_dirty_tree failed for %s", repo_path, exc_info=True)
        return None


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
