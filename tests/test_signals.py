"""Tests for labro.signals — GitHub API signal collection.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import json
import subprocess
from typing import Any
from unittest.mock import patch

from labro.signals import ItemSignals, _count_reactions, collect


def _completed(json_data: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["gh", "api", "--paginate", "dummy"],
        returncode=0,
        stdout=json.dumps(json_data),
        stderr="",
    )


# ── Issue tests ────────────────────────────────────────────────────────────────


def test_collect_issue_closed_completed() -> None:
    """An issue with state=closed and no state_reason → closed_completed."""
    calls: list[str] = []

    def fake_run(
        args: list[str], *args2: object, **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        url: str = args[-1]
        calls.append(url)
        if "reactions" in url:
            return _completed([])
        return _completed({"state": "closed", "state_reason": None})

    with patch("labro.signals.subprocess.run", side_effect=fake_run):
        result = collect("org/repo", "issue", 1, "2024-01-01T00:00:00Z")

    assert result == ItemSignals(
        outcome_state="closed_completed",
        follow_up_commits=None,
        thumbs_up=0,
        thumbs_down=0,
    )
    assert len(calls) == 2


def test_collect_issue_closed_not_planned() -> None:
    """An issue with state=closed and state_reason=not_planned → closed_not_planned."""

    def fake_run(
        args: list[str], *args2: object, **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        url: str = args[-1]
        if "reactions" in url:
            return _completed([])
        return _completed({"state": "closed", "state_reason": "not_planned"})

    with patch("labro.signals.subprocess.run", side_effect=fake_run):
        result = collect("org/repo", "issue", 2, "2024-01-01T00:00:00Z")

    assert result.outcome_state == "closed_not_planned"
    assert result.follow_up_commits is None


def test_collect_issue_closed_duplicate() -> None:
    """An issue with state=closed and state_reason=duplicate → closed_duplicate."""

    def fake_run(
        args: list[str], *args2: object, **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        url: str = args[-1]
        if "reactions" in url:
            return _completed([])
        return _completed({"state": "closed", "state_reason": "duplicate"})

    with patch("labro.signals.subprocess.run", side_effect=fake_run):
        result = collect("org/repo", "issue", 4, "2024-01-01T00:00:00Z")

    assert result.outcome_state == "closed_duplicate"
    assert result.follow_up_commits is None


def test_collect_issue_open() -> None:
    """An open issue → outcome_state='open'."""

    def fake_run(
        args: list[str], *args2: object, **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        url: str = args[-1]
        if "reactions" in url:
            return _completed([])
        return _completed({"state": "open", "state_reason": None})

    with patch("labro.signals.subprocess.run", side_effect=fake_run):
        result = collect("org/repo", "issue", 3, "2024-01-01T00:00:00Z")

    assert result.outcome_state == "open"


# ── PR tests ───────────────────────────────────────────────────────────────────


def test_collect_pr_merged() -> None:
    """A merged PR → outcome_state='merged', follow_up_commits counted."""
    calls: list[str] = []

    def fake_run(
        args: list[str], *args2: object, **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        url: str = args[-1]
        calls.append(url)
        if "reactions" in url:
            return _completed([])
        if "commits" in url:
            return _completed(
                [
                    {"commit": {"committer": {"date": "2024-06-01T00:00:00Z"}}},
                    {"commit": {"committer": {"date": "2024-01-01T00:00:00Z"}}},
                ]
            )
        return _completed({"state": "closed", "merged_at": "2024-06-02T00:00:00Z"})

    with patch("labro.signals.subprocess.run", side_effect=fake_run):
        result = collect("org/repo", "pr", 10, "2024-01-15T00:00:00Z")

    assert result == ItemSignals(
        outcome_state="merged",
        follow_up_commits=1,
        thumbs_up=0,
        thumbs_down=0,
    )
    assert len(calls) == 3


def test_collect_pr_closed_unmerged() -> None:
    """A closed PR without merged_at → outcome_state='closed_unmerged'."""

    def fake_run(
        args: list[str], *args2: object, **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        url: str = args[-1]
        if "reactions" in url:
            return _completed([])
        if "commits" in url:
            return _completed([])
        return _completed({"state": "closed", "merged_at": None})

    with patch("labro.signals.subprocess.run", side_effect=fake_run):
        result = collect("org/repo", "pr", 11, "2024-01-01T00:00:00Z")

    assert result.outcome_state == "closed_unmerged"


def test_collect_reactions_counted() -> None:
    """Thumbs-up and thumbs-down are correctly counted from reactions."""

    def fake_run(
        args: list[str], *args2: object, **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        url: str = args[-1]
        if "reactions" in url:
            return _completed(
                [
                    {"content": "+1"},
                    {"content": "+1"},
                    {"content": "-1"},
                    {"content": "heart"},
                    {"content": "+1"},
                ]
            )
        return _completed({"state": "open", "state_reason": None})

    with patch("labro.signals.subprocess.run", side_effect=fake_run):
        result = collect("org/repo", "issue", 5, "2024-01-01T00:00:00Z")

    assert result.thumbs_up == 3
    assert result.thumbs_down == 1


# ── Bot-scoped reaction tests ──────────────────────────────────────────────────


def _item_response(user: str, state: str = "open") -> Any:
    return {"state": state, "state_reason": None, "user": {"login": user}}


def _bot_comment(cid: int, user: str) -> Any:
    return {"id": cid, "user": {"login": user}, "body": "Bot says hi"}


def test_bot_reactions_item_author_matches() -> None:
    """When bot_username matches the item author, body reactions are counted."""

    def fake_run(
        args: list[str], *args2: object, **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        url: str = args[-1]
        # First call: fetch item → bot-authored
        if "comments" not in url and "reactions" not in url:
            return _completed(_item_response("my-bot[bot]"))
        # Body reactions endpoint
        if "comments" not in url and "reactions" in url and "comments" not in url.split("/"):
            return _completed([{"content": "+1"}, {"content": "+1"}])
        # Comments list → no comments
        if "comments" in url and "reactions" not in url:
            return _completed([])
        return _completed([])

    with patch("labro.signals.subprocess.run", side_effect=fake_run):
        result = collect(
            "org/repo", "issue", 1, "2024-01-01T00:00:00Z", bot_username="my-bot[bot]"
        )

    assert result.thumbs_up == 2
    assert result.thumbs_down == 0


def test_bot_reactions_item_author_differs() -> None:
    """When bot_username differs from the item author, body reactions are skipped."""

    def fake_run(
        args: list[str], *args2: object, **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        url: str = args[-1]
        if "comments" not in url and "reactions" not in url:
            return _completed(_item_response("human-user"))
        if "comments" in url and "reactions" not in url:
            return _completed([])
        return _completed([])

    with patch("labro.signals.subprocess.run", side_effect=fake_run):
        result = collect(
            "org/repo", "issue", 1, "2024-01-01T00:00:00Z", bot_username="my-bot[bot]"
        )

    assert result.thumbs_up == 0
    assert result.thumbs_down == 0


def test_bot_reactions_comment_reactions_counted() -> None:
    """Reactions on bot-authored comments are counted."""

    def fake_run(
        args: list[str], *args2: object, **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        url: str = args[-1]
        # Fetch item
        if "comments" not in url and "reactions" not in url:
            return _completed(_item_response("human-user"))
        # Fetch comments → one bot comment, one human comment
        if "comments" in url and "reactions" not in url:
            return _completed(
                [
                    _bot_comment(101, "my-bot[bot]"),
                    _bot_comment(102, "human-user"),
                ]
            )
        # Fetch reactions on comment 101
        if "comments/101" in url:
            return _completed([{"content": "+1"}, {"content": "-1"}, {"content": "-1"}])
        # Fetch reactions on comment 102 — should not be called, but handle gracefully
        return _completed([])

    with patch("labro.signals.subprocess.run", side_effect=fake_run):
        result = collect(
            "org/repo", "issue", 1, "2024-01-01T00:00:00Z", bot_username="my-bot[bot]"
        )

    assert result.thumbs_up == 1
    assert result.thumbs_down == 2


def test_bot_reactions_item_and_comment() -> None:
    """Reactions on both bot body and bot comments are summed."""

    def fake_run(
        args: list[str], *args2: object, **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        url: str = args[-1]
        if "comments" not in url and "reactions" not in url:
            return _completed(_item_response("my-bot[bot]"))
        if "comments" in url and "reactions" not in url:
            return _completed([_bot_comment(201, "my-bot[bot]")])
        if "comments/201" in url:
            return _completed([{"content": "+1"}, {"content": "+1"}, {"content": "+1"}])
        return _completed([{"content": "+1"}])  # body reactions

    with patch("labro.signals.subprocess.run", side_effect=fake_run):
        result = collect(
            "org/repo", "issue", 1, "2024-01-01T00:00:00Z", bot_username="my-bot[bot]"
        )

    assert result.thumbs_up == 4  # 1 body + 3 comment
    assert result.thumbs_down == 0


def test_count_reactions_empty() -> None:
    """_count_reactions returns (0, 0) for an empty list."""
    up, down = _count_reactions([])
    assert up == 0
    assert down == 0


def test_count_reactions_mixed() -> None:
    """_count_reactions correctly tallies +1 and -1, ignoring other content types."""
    data = [{"content": "+1"}, {"content": "-1"}, {"content": "heart"}, {"content": "+1"}]
    up, down = _count_reactions(data)
    assert up == 2
    assert down == 1
