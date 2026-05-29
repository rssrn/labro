"""Claude assignee signalling — assign a GitHub user during a run, restore after.

Assigns a configured GitHub user (e.g. "claude-code-youruser") to the task item
before the agent runs and restores the original assignees afterwards, regardless
of whether the run succeeds or fails.

Both functions are soft-fail: gh errors are logged as warnings and never re-raised
so that a missing collaborator or API hiccup cannot abort or corrupt a run.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import logging
import subprocess

from labro.models import Task

logger = logging.getLogger(__name__)


def _gh_edit_assignees(
    item_type: str,
    item_number: int,
    repo: str,
    *,
    add: list[str],
    remove: list[str],
) -> None:
    """Edit assignees on a GitHub issue or PR via gh CLI (list-form, shell=False)."""
    if not add and not remove:
        return
    cmd = ["gh", item_type, "edit", str(item_number), "--repo", repo]
    for user in add:
        cmd += ["--add-assignee", user]
    for user in remove:
        cmd += ["--remove-assignee", user]
    result = subprocess.run(cmd, capture_output=True, text=True)  # shell=False (default)
    if result.returncode != 0:
        logger.warning(
            "gh %s edit assignees failed (rc=%d): %s",
            item_type,
            result.returncode,
            result.stderr.strip(),
        )


def assign_claude(task: Task, claude_user: str, *, dry_run: bool = False) -> None:
    """Assign *claude_user* to the GitHub item referenced by *task*.

    No-op if the task has no item_type or item_number (e.g. grafana-alerts tasks
    before the agent creates a tracking issue).  Soft-fail on gh errors.
    """
    if task.item_type is None or task.item_number is None:
        return
    if dry_run:
        logger.info(
            "dry-run: would assign %s to %s #%d in %s",
            claude_user,
            task.item_type,
            task.item_number,
            task.repo,
        )
        return
    logger.info(
        "assigning %s to %s #%d in %s",
        claude_user,
        task.item_type,
        task.item_number,
        task.repo,
    )
    _gh_edit_assignees(
        task.item_type,
        task.item_number,
        task.repo,
        add=[claude_user],
        remove=[],
    )


def restore_assignees(task: Task, claude_user: str, *, dry_run: bool = False) -> None:
    """Remove *claude_user* and restore original assignees on the GitHub item.

    Original assignees are read from ``task.assignees`` (captured at task-selection
    time).  If the list is empty, the item is left unassigned after removing
    *claude_user*.  Soft-fail on gh errors.
    """
    if task.item_type is None or task.item_number is None:
        return
    if dry_run:
        logger.info(
            "dry-run: would restore assignees %r on %s #%d in %s (removing %s)",
            task.assignees,
            task.item_type,
            task.item_number,
            task.repo,
            claude_user,
        )
        return
    logger.info(
        "restoring assignees on %s #%d in %s (removing %s, adding %r)",
        task.item_type,
        task.item_number,
        task.repo,
        claude_user,
        task.assignees,
    )
    _gh_edit_assignees(
        task.item_type,
        task.item_number,
        task.repo,
        add=list(task.assignees),
        remove=[claude_user],
    )
