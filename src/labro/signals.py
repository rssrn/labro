"""GitHub API signal collection for items_touched.

Collects outcome state, thumbs-up/down, and follow-up commits (PRs only)
by querying the GitHub API via ``gh api`` subprocess calls.

All subprocess calls use list-form args with shell=False.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any


@dataclass
class ItemSignals:
    outcome_state: str | None
    follow_up_commits: int | None
    thumbs_up: int
    thumbs_down: int


def collect(
    repo: str,
    item_type: str,
    item_number: int,
    run_started_at: str,
    bot_username: str | None = None,
) -> ItemSignals:
    """Query the GitHub API for engagement signals on a single item.

    When *bot_username* is provided, thumbs-up/down are only counted on:
    - The body of items authored by the bot
    - Comments authored by the bot
    This scopes the signal to reactions the bot can actually influence.

    Args:
        repo: ``owner/repo`` string.
        item_type: ``"issue"`` or ``"pr"``.
        item_number: GitHub issue/PR number.
        run_started_at: ISO 8601 UTC timestamp of the run that touched this item.
        bot_username: GitHub username of the bot (e.g. ``"my-app[bot]"``).
            When ``None``, counts reactions on the item body from any user
            (legacy behaviour).

    Returns:
        An :class:`ItemSignals` dataclass with the collected signals.

    Raises:
        subprocess.CalledProcessError: if a ``gh api`` call exits non-zero.
        json.JSONDecodeError: if the API response is not valid JSON.
    """
    if item_type == "pr":
        outcome_state, follow_up_commits, thumbs_up, thumbs_down = _collect_pr(
            repo, item_number, run_started_at, bot_username=bot_username
        )
        return ItemSignals(
            outcome_state=outcome_state,
            follow_up_commits=follow_up_commits,
            thumbs_up=thumbs_up,
            thumbs_down=thumbs_down,
        )
    outcome_state, thumbs_up, thumbs_down = _collect_issue(
        repo, item_number, bot_username=bot_username
    )
    return ItemSignals(
        outcome_state=outcome_state,
        follow_up_commits=None,
        thumbs_up=thumbs_up,
        thumbs_down=thumbs_down,
    )


def _run_gh_api(url: str) -> Any:
    """Run ``gh api --paginate <url>`` (list-form, shell=False) and return parsed JSON.

    Raises:
        subprocess.CalledProcessError: if gh exits non-zero.
        json.JSONDecodeError: if stdout is not valid JSON.
    """
    result = subprocess.run(
        ["gh", "api", "--paginate", url],
        capture_output=True,
        text=True,
        check=True,
        shell=False,
    )
    return json.loads(result.stdout)


def _collect_issue(
    repo: str, number: int, bot_username: str | None = None
) -> tuple[str | None, int, int]:
    """Collect signals for an issue.

    Returns:
        A tuple of ``(outcome_state, thumbs_up, thumbs_down)``.
    """
    outcome_state = _fetch_outcome_state(repo, number)
    thumbs_up, thumbs_down = _fetch_reactions(repo, number, bot_username=bot_username)
    return outcome_state, thumbs_up, thumbs_down


def _collect_pr(
    repo: str,
    number: int,
    run_started_at: str,
    bot_username: str | None = None,
) -> tuple[str | None, int | None, int, int]:
    """Collect signals for a pull request.

    Returns:
        A tuple of ``(outcome_state, follow_up_commits, thumbs_up, thumbs_down)``.
    """
    outcome_state = _fetch_pr_state(repo, number)
    thumbs_up, thumbs_down = _fetch_reactions(repo, number, bot_username=bot_username)
    follow_up_commits = _fetch_follow_up_commits(repo, number, run_started_at)
    return outcome_state, follow_up_commits, thumbs_up, thumbs_down


def _fetch_outcome_state(repo: str, number: int) -> str:
    """Determine the outcome state for an issue via the GitHub API.

    Maps ``state`` / ``state_reason`` to:
      - open → ``"open"``
      - closed + state_reason == ``"not_planned"`` → ``"closed_not_planned"``
      - closed + state_reason == ``"duplicate"`` → ``"closed_duplicate"``
      - closed + anything else → ``"closed_completed"``
    """
    data = _run_gh_api(f"repos/{repo}/issues/{number}")
    if isinstance(data, list):
        data = data[0] if data else {}
    state: str = data.get("state", "")
    if state == "open":
        return "open"
    state_reason: str | None = data.get("state_reason")
    if state_reason == "not_planned":
        return "closed_not_planned"
    if state_reason == "duplicate":
        return "closed_duplicate"
    return "closed_completed"


def _fetch_pr_state(repo: str, number: int) -> str:
    """Determine the outcome state for a pull request via the GitHub API.

    Maps ``state`` / ``merged_at`` to:
      - merged_at non-null → ``"merged"``
      - state == ``"closed"`` → ``"closed_unmerged"``
      - state == ``"open"`` → ``"open"``
    """
    data = _run_gh_api(f"repos/{repo}/pulls/{number}")
    if isinstance(data, list):
        data = data[0] if data else {}
    merged_at: str | None = data.get("merged_at")
    if merged_at is not None:
        return "merged"
    state: str = data.get("state", "")
    if state == "closed":
        return "closed_unmerged"
    return "open"


def _count_reactions(data: Any) -> tuple[int, int]:
    """Count +1 / -1 reactions from a reactions API response."""
    if isinstance(data, dict):
        data = [data]
    thumbs_up = sum(1 for r in data if r.get("content") == "+1")
    thumbs_down = sum(1 for r in data if r.get("content") == "-1")
    return thumbs_up, thumbs_down


def _fetch_reactions(repo: str, number: int, bot_username: str | None = None) -> tuple[int, int]:
    """Fetch thumbs-up/down on bot-authored content only.

    When *bot_username* is set, only count reactions on:
    - The issue/PR body, if the item author matches *bot_username*.
    - Comments authored by *bot_username*.

    When *bot_username* is ``None``, count all reactions on the item body
    (legacy behaviour).
    """
    total_up = 0
    total_down = 0

    if bot_username is None:
        return _count_reactions(_run_gh_api(f"repos/{repo}/issues/{number}/reactions"))

    # Fetch the item to check the author.
    item = _run_gh_api(f"repos/{repo}/issues/{number}")
    if isinstance(item, list):
        item = item[0] if item else {}
    author: str = (item.get("user") or {}).get("login", "")
    if author == bot_username:
        up, down = _count_reactions(_run_gh_api(f"repos/{repo}/issues/{number}/reactions"))
        total_up += up
        total_down += down

    # Fetch comments; filter to bot-authored; count their reactions.
    comments = _run_gh_api(f"repos/{repo}/issues/{number}/comments?per_page=100")
    if isinstance(comments, dict):
        comments = [comments]
    for comment in comments:
        comment_author: str | None = (comment.get("user") or {}).get("login")
        if comment_author == bot_username:
            cid: int = comment["id"]
            up, down = _count_reactions(
                _run_gh_api(f"repos/{repo}/issues/comments/{cid}/reactions")
            )
            total_up += up
            total_down += down

    return total_up, total_down


def _fetch_follow_up_commits(repo: str, number: int, run_started_at: str) -> int | None:
    """Count commits pushed to the PR after ``run_started_at``.

    Returns None when the PR has no commits (should not happen in practice).
    """
    data = _run_gh_api(f"repos/{repo}/pulls/{number}/commits")
    if isinstance(data, dict):
        data = [data]
    if not data:
        return None
    count = 0
    for commit in data:
        committer = commit.get("commit", {}).get("committer", {})
        date_str: str | None = committer.get("date")
        if date_str is not None and date_str > run_started_at:
            count += 1
    return count
