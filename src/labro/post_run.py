"""Post-run label transitions and failure comments for gh-label tasks.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import logging
import subprocess

from labro.models import AgentResult, Task

logger = logging.getLogger(__name__)

_GENERIC_FAILURE_MSG = (
    "Labro attempted to work on this item but the agent did not complete successfully. "
    "Remove the `ai-failed` and `ai-contributed` labels to re-queue the item."
)

_AI_HANDOVER_LABEL = "ai-handover"


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
    agent_name: str = "claude-code",
    wip_branch_url: str | None = None,
    resuming_wip: bool = False,
) -> None:
    """Apply label transitions and post failure/handover comments after a run.

    Args:
        run_id: Run identifier (informational; not used in gh calls).
        task: The task that was executed.
        agent_result: Structured result from the agent, or None on timeout/error.
        outcome: ``"success"``, ``"failure"``, or ``"partial"``.
        agent_name: Agent identifier string (e.g. ``"claude-code"``).
        wip_branch_url: URL of the preserved WIP branch, if one was created.
        resuming_wip: True if this run resumed from a prior WIP branch (changes
            the branch-reference wording in the handover comment).
    """
    if task.source != "gh-label" or task.item_number is None:
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
    elif outcome == "partial":
        _gh_edit(
            item_type, item_number, repo, add=[_AI_HANDOVER_LABEL, "ai-contributed"], remove=[]
        )
        progress = (agent_result.summary or "") if agent_result is not None else ""
        parts: list[str] = [
            f"Labro's agent (`{agent_name}`) ran out of turns before completing this {item_type}."
        ]
        if progress:
            parts.append(f"\n\n**Progress so far:**\n{progress}")
        if wip_branch_url:
            if resuming_wip:
                parts.append(
                    f"\n\nExisting WIP branch updated with latest progress: {wip_branch_url}"
                )
            else:
                parts.append(f"\n\nWork in progress preserved on new branch: {wip_branch_url}")
        parts.append("\n\nRemove the `ai-handover` label to re-queue this item.")
        _gh_comment(item_type, item_number, repo, "".join(parts))
    elif agent_result is not None and agent_result.failure_reason == "session_limit_hit":
        # Session limit was hit before (or part-way through) the run.  The issue was
        # never fully worked on, so we must not block re-queuing with ai-failed.
        if wip_branch_url:
            # Agent did partial work before hitting the limit — treat like a partial run.
            _gh_edit(
                item_type, item_number, repo, add=[_AI_HANDOVER_LABEL, "ai-contributed"], remove=[]
            )
            parts = [
                f"Labro's agent (`{agent_name}`) hit the session limit"
                f" mid-run on this {item_type}."
            ]
            if agent_result.summary:
                parts.append(f"\n\n**Progress so far:**\n{agent_result.summary}")
            parts.append(f"\n\nWork in progress preserved on branch: {wip_branch_url}")
            parts.append("\n\nRemove the `ai-handover` label to re-queue this item.")
            _gh_comment(item_type, item_number, repo, "".join(parts))
        else:
            # Agent produced no output — issue is untouched, leave labels alone so it
            # will be picked up automatically when budget resets.
            _gh_comment(
                item_type,
                item_number,
                repo,
                f"Labro skipped this {item_type}: the Claude session limit was reached"
                f" ({agent_result.summary}). "
                f"It will be re-queued automatically once the session resets.",
            )
    else:
        _gh_edit(item_type, item_number, repo, add=["ai-failed", "ai-contributed"], remove=[])
        if agent_result is not None:
            detail = agent_result.failure_reason or agent_result.summary
            body = (
                f"Labro's agent (`{agent_name}`) was assigned this {item_type}"
                f" but reported failure.\n\n**Reason:** {detail}"
                if detail
                else _GENERIC_FAILURE_MSG
            )
        else:
            body = _GENERIC_FAILURE_MSG
        if wip_branch_url:
            body += f"\n\nWork in progress preserved on branch: {wip_branch_url}"
        _gh_comment(item_type, item_number, repo, body)
