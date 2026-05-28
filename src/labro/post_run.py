"""Post-run label transitions and failure comments for gh-delegated tasks.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import logging
import subprocess

from labro.models import AgentResult, Task

logger = logging.getLogger(__name__)

_GENERIC_FAILURE_MSG = (
    "Labro attempted to work on this item but the agent did not complete successfully. "
    "Remove this label and the ai-failed label to re-queue the item."
)


def _ensure_labels(repo: str, labels: list[str]) -> None:
    """Create any labels that don't already exist in the repo.

    Uses ``gh label create --force`` which is a no-op if the label exists.
    Failures are logged as warnings and never raised.
    """
    for label in labels:
        result = subprocess.run(
            ["gh", "label", "create", label, "--repo", repo, "--force"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.warning(
                "gh label create failed for %r (rc=%d): %s",
                label,
                result.returncode,
                result.stderr.strip(),
            )


def _gh_edit(
    item_type: str, item_number: int, repo: str, add: list[str], remove: list[str]
) -> None:
    """Run `gh issue/pr edit` to add/remove labels. Logs a warning on failure."""
    if add:
        _ensure_labels(repo, add)
    cmd = ["gh", f"{item_type}", "edit", str(item_number), "--repo", repo]
    for label in add:
        cmd += ["--add-label", label]
    for label in remove:
        cmd += ["--remove-label", label]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.warning(
            "gh %s edit failed (rc=%d): %s", item_type, result.returncode, result.stderr.strip()
        )


def _gh_comment(item_type: str, item_number: int, repo: str, body: str) -> None:
    """Post a comment on a GitHub issue or PR. Logs a warning on failure."""
    result = subprocess.run(
        ["gh", f"{item_type}", "comment", str(item_number), "--repo", repo, "--body", body],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.warning(
            "gh %s comment failed (rc=%d): %s", item_type, result.returncode, result.stderr.strip()
        )


def post_run(
    run_id: str,
    task: Task,
    agent_result: AgentResult | None,
    *,
    outcome: str,
) -> None:
    """Apply label transitions and post failure comments after a run.

    Args:
        run_id: Run identifier (informational; not used in gh calls).
        task: The task that was executed.
        agent_result: Structured result from the agent, or None on timeout/error.
        outcome: ``"success"`` or ``"failure"`` as mapped by cli.py.
    """
    if task.source != "gh-delegated" or task.item_number is None:
        return

    item_type = task.item_type or "issue"
    item_number = task.item_number
    repo = task.repo

    if outcome == "success":
        add_labels = []
        if task.done_label:
            add_labels.append(task.done_label)
        add_labels.append("ai-contributed")
        remove_labels = [task.source_label] if task.source_label else []
        _gh_edit(item_type, item_number, repo, add=add_labels, remove=remove_labels)
    else:
        _gh_edit(item_type, item_number, repo, add=["ai-failed", "ai-contributed"], remove=[])
        if agent_result is not None:
            body = agent_result.failure_reason or agent_result.summary or _GENERIC_FAILURE_MSG
        else:
            body = _GENERIC_FAILURE_MSG
        _gh_comment(item_type, item_number, repo, body)
