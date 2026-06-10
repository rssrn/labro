"""Post-run label transitions and failure comments.

Handles gh-label and proactive-improvement task sources.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from urllib.parse import quote

from labro.models import AgentConfig, AgentResult, Task

logger = logging.getLogger(__name__)

_GENERIC_FAILURE_MSG = (
    "Labro attempted to work on this item but the agent did not complete successfully. "
    "Remove the `ai-failed` and `ai-contributed` labels to re-queue the item."
)

_AI_HANDOVER_LABEL = "ai-handover"


@dataclass
class PreRunHandle:
    """Opaque context returned by pre_run; passed to append_fallback_note.

    Exactly one of comment_id or issue_number will be set depending on task source.
    """

    repo: str
    comment_id: int | None = None  # gh-label/gh-author: comment body to edit
    issue_number: int | None = None  # proactive-improvement: issue body to edit


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
    """Add/remove labels on an issue or PR. Logs a warning on failure; never raises.

    Routed through the REST API (`gh api`) rather than `gh issue/pr edit`: the
    latter's GraphQL flow fetches the now-sunset Projects (classic)
    ``projectCards`` field, which GitHub answers with a NOT_FOUND error, failing
    the whole edit (rc=1) and silently dropping the label transition. The REST
    ``issues`` labels endpoint serves PRs too, so one path covers both.

    @author Claude Opus 4.8 Anthropic
    """
    if add:
        _ensure_labels(repo, add)
        add_args: list[str] = []
        for label in add:
            add_args += ["-f", f"labels[]={label}"]
        result = subprocess.run(
            [
                "gh",
                "api",
                "--method",
                "POST",
                f"repos/{repo}/issues/{item_number}/labels",
                *add_args,
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.warning(
                "gh api add-label failed for %s #%d (rc=%d): %s",
                item_type,
                item_number,
                result.returncode,
                result.stderr.strip(),
            )
            return

    for label in remove:
        result = subprocess.run(
            [
                "gh",
                "api",
                "--method",
                "DELETE",
                f"repos/{repo}/issues/{item_number}/labels/{quote(label, safe='')}",
            ],
            capture_output=True,
            text=True,
        )
        # A 404 means the label was already absent — not worth surfacing.
        if result.returncode != 0 and "404" not in result.stderr:
            logger.warning(
                "gh api remove-label %r failed for %s #%d (rc=%d): %s",
                label,
                item_type,
                item_number,
                result.returncode,
                result.stderr.strip(),
            )

    changes = [f"+{label}" for label in add] + [f"-{label}" for label in remove]
    logger.info("labelled %s #%d: %s", item_type, item_number, " ".join(changes))


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


def _gh_comment_create(item_number: int, repo: str, body: str) -> int | None:
    """Post a comment via the REST API and return its comment ID, or None on failure."""
    import json as _json

    result = subprocess.run(
        [
            "gh",
            "api",
            "--method",
            "POST",
            f"repos/{repo}/issues/{item_number}/comments",
            "-f",
            f"body={body}",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.warning(
            "gh api create comment failed for #%d (rc=%d): %s",
            item_number,
            result.returncode,
            result.stderr.strip(),
        )
        return None
    try:
        return int(_json.loads(result.stdout)["id"])
    except (KeyError, ValueError, _json.JSONDecodeError) as exc:
        logger.warning("gh api create comment: could not parse comment id: %s", exc)
        return None


def _gh_comment_edit(comment_id: int, repo: str, body: str) -> None:
    """Replace the body of an existing comment. Logs a warning on failure."""
    result = subprocess.run(
        [
            "gh",
            "api",
            "--method",
            "PATCH",
            f"repos/{repo}/issues/comments/{comment_id}",
            "-f",
            f"body={body}",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.warning(
            "gh api edit comment %d failed (rc=%d): %s",
            comment_id,
            result.returncode,
            result.stderr.strip(),
        )


def _gh_issue_fetch_body(issue_number: int, repo: str) -> str | None:
    """Fetch an issue body via the REST API. Returns None on failure."""
    import json as _json

    result = subprocess.run(
        ["gh", "api", f"repos/{repo}/issues/{issue_number}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.warning(
            "gh api fetch issue %d failed (rc=%d): %s",
            issue_number,
            result.returncode,
            result.stderr.strip(),
        )
        return None
    try:
        return str(_json.loads(result.stdout)["body"])
    except (KeyError, ValueError, _json.JSONDecodeError) as exc:
        logger.warning("gh api fetch issue %d: could not parse body: %s", issue_number, exc)
        return None


def _gh_issue_edit_body(issue_number: int, repo: str, body: str) -> None:
    """Replace an issue body via the REST API. Logs a warning on failure."""
    result = subprocess.run(
        [
            "gh",
            "api",
            "--method",
            "PATCH",
            f"repos/{repo}/issues/{issue_number}",
            "-f",
            f"body={body}",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.warning(
            "gh api edit issue %d failed (rc=%d): %s",
            issue_number,
            result.returncode,
            result.stderr.strip(),
        )


def pre_run(task: Task, agent_cfg: AgentConfig) -> PreRunHandle | None:
    """Post a pre-run marker and return a handle for appending fallback notes.

    For gh-label/gh-author tasks: posts a 'Labro picking up' comment and
    returns a handle containing the comment ID.
    For proactive-improvement tasks: no comment is posted; returns a handle
    containing the issue number so fallback notes can be appended to the body.
    Returns None if the task has no item_number.

    @author Claude Sonnet 4.6 Anthropic
    """
    if task.item_number is None:
        return None
    if task.source == "proactive-improvement":
        return PreRunHandle(repo=task.repo, issue_number=task.item_number)
    parts = ["Labro picking up"]
    if task.source_label:
        parts.append(f", selected based on `#{task.source_label}` label")
    parts.append(f". Assigning to `{agent_cfg.slug}`.")
    comment_id = _gh_comment_create(task.item_number, task.repo, "".join(parts))
    if comment_id is None:
        return None
    return PreRunHandle(repo=task.repo, comment_id=comment_id)


def append_fallback_note(
    handle: PreRunHandle,
    failed_slug: str,
    reason: str,
    next_slug: str,
) -> None:
    """Append a fallback note to the pre-run comment or proactive issue body.

    For gh-label/gh-author: fetches the comment and PATCHes it with a new line.
    For proactive-improvement: fetches the issue body and PATCHes it with a new line.
    Soft-fail on any gh error.

    @author Claude Sonnet 4.6 Anthropic
    """
    note = f"Model `{failed_slug}` failed: {reason}. Trying fallback with `{next_slug}`."

    if handle.comment_id is not None:
        import json as _json

        fetch = subprocess.run(
            ["gh", "api", f"repos/{handle.repo}/issues/comments/{handle.comment_id}"],
            capture_output=True,
            text=True,
        )
        if fetch.returncode != 0:
            logger.warning(
                "gh api fetch comment %d failed (rc=%d): %s",
                handle.comment_id,
                fetch.returncode,
                fetch.stderr.strip(),
            )
            return
        try:
            current_body: str = _json.loads(fetch.stdout)["body"]
        except (KeyError, ValueError, _json.JSONDecodeError) as exc:
            logger.warning(
                "gh api fetch comment %d: could not parse body: %s", handle.comment_id, exc
            )
            return
        _gh_comment_edit(handle.comment_id, handle.repo, f"{current_body}\n{note}")

    elif handle.issue_number is not None:
        issue_body = _gh_issue_fetch_body(handle.issue_number, handle.repo)
        if issue_body is None:
            return
        _gh_issue_edit_body(handle.issue_number, handle.repo, f"{issue_body}\n{note}")


def post_run(
    run_id: str,
    task: Task,
    agent_result: AgentResult | None,
    *,
    outcome: str,
    agent_name: str = "labro-agent",
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
    if task.source == "proactive-improvement":
        _post_run_proactive(task, agent_result, outcome=outcome, agent_name=agent_name)
        return

    if task.source not in {"gh-label", "gh-author"} or task.item_number is None:
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
            # remains eligible for future runs.
            _gh_comment(
                item_type,
                item_number,
                repo,
                f"Labro skipped this {item_type}: the agent session limit was reached"
                f" ({agent_result.summary}). "
                f"This {item_type} remains eligible to be picked in future runs.",
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


def _post_run_proactive(
    task: Task,
    agent_result: AgentResult | None,
    *,
    outcome: str,
    agent_name: str,
) -> None:
    """Apply labels and post comments on the harness-created proactive suggestion issue."""
    if task.item_number is None:
        return

    repo = task.repo
    item_number = task.item_number

    if outcome == "success":
        _gh_edit("issue", item_number, repo, add=["ai-contributed"], remove=[])
    else:
        detail: str | None = None
        if agent_result is not None:
            detail = agent_result.failure_reason or agent_result.summary
        body = (
            f"Labro's agent (`{agent_name}`) investigated this suggestion"
            f" but reported failure.\n\n**Reason:** {detail}"
            if detail
            else _GENERIC_FAILURE_MSG
        )
        _gh_comment("issue", item_number, repo, body)
        _gh_edit("issue", item_number, repo, add=["ai-failed", "ai-contributed"], remove=[])
