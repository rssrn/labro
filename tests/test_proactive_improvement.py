"""Tests for task_sources/proactive_improvement.py.

Covers:
- Cap check: source returns None when open suggestions >= max_open_suggestions
- Cap check: source proceeds when below cap
- Perspective selection: chosen_name and perspective_prompt set when perspectives available
- Perspective selection: empty when no perspectives loaded
- Perspective subsetting: source-level perspectives list restricts candidates
- Harness creates issue: returned Task has correct item_type, item_number, item_url
- Failure: returns None when gh issue create fails

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import json
from subprocess import CalledProcessError
from unittest.mock import MagicMock, patch

from labro.config.schema import (
    PermittedAction,
    PerspectiveConfig,
    ProjectConfig,
)
from labro.config.schema import (
    ProactiveImprovementSource as ProactiveImprovementSourceConfig,
)
from labro.task_sources.proactive_improvement import ProactiveImprovementTaskSource

# ── Helpers ────────────────────────────────────────────────────────────────────


def _project(repo: str = "org/repo") -> ProjectConfig:
    return ProjectConfig(
        name="test-proj",
        repo=repo,
        cron="0 * * * *",
        model=["claude-code:anthropic/claude-sonnet-4-6"],
    )


def _source_cfg(**kwargs: object) -> ProactiveImprovementSourceConfig:
    defaults: dict[str, object] = {
        "type": "proactive-improvement",
        "max_open_suggestions": 3,
    }
    defaults.update(kwargs)
    return ProactiveImprovementSourceConfig(**defaults)  # type: ignore[arg-type]


def _perspectives() -> dict[str, PerspectiveConfig]:
    return {
        "red-team": PerspectiveConfig(prompt="Look for failures."),
        "pre-mortem": PerspectiveConfig(prompt="Assume it fails."),
    }


def _make_source(
    source_cfg: ProactiveImprovementSourceConfig | None = None,
    perspectives: dict[str, PerspectiveConfig] | None = None,
) -> ProactiveImprovementTaskSource:
    return ProactiveImprovementTaskSource(
        source_config=source_cfg or _source_cfg(),
        personas={},
        perspectives=perspectives if perspectives is not None else _perspectives(),
    )


def _gh_list_response(count: int) -> str:
    return json.dumps([{"number": i + 1} for i in range(count)])


def _gh_create_response(number: int = 99, repo: str = "org/repo") -> str:
    return f"https://github.com/{repo}/issues/{number}\n"


def _fetch_defaults() -> dict[str, object]:
    return {
        "defaults_model": ["claude-code:anthropic/claude-sonnet-4-6"],
        "defaults_max_turns": 20,
        "defaults_timeout_s": 600,
        "defaults_max_comments": 10,
    }


# ── Cap check ─────────────────────────────────────────────────────────────────


def test_cap_check_returns_none_when_at_cap() -> None:
    source = _make_source(_source_cfg(max_open_suggestions=2))
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout=_gh_list_response(2), returncode=0)
        result = source.fetch_task(_project(), **_fetch_defaults())  # type: ignore[arg-type]
    assert result is None


def test_cap_check_returns_none_when_above_cap() -> None:
    source = _make_source(_source_cfg(max_open_suggestions=2))
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout=_gh_list_response(5), returncode=0)
        result = source.fetch_task(_project(), **_fetch_defaults())  # type: ignore[arg-type]
    assert result is None


def test_cap_check_proceeds_when_below_cap() -> None:
    source = _make_source(_source_cfg(max_open_suggestions=3))
    responses = [
        MagicMock(stdout=_gh_list_response(1), returncode=0),  # cap check
        MagicMock(returncode=0),  # ensure label
        MagicMock(stdout=_gh_create_response(), returncode=0),  # issue create
    ]
    with patch("subprocess.run", side_effect=responses):
        result = source.fetch_task(_project(), **_fetch_defaults())  # type: ignore[arg-type]
    assert result is not None


def test_cap_check_gh_failure_returns_none() -> None:
    source = _make_source()
    with patch("subprocess.run", side_effect=CalledProcessError(1, "gh")):
        result = source.fetch_task(_project(), **_fetch_defaults())  # type: ignore[arg-type]
    assert result is None


# ── Perspective selection ──────────────────────────────────────────────────────


def test_perspective_set_when_perspectives_available() -> None:
    source = _make_source(
        perspectives={"red-team": PerspectiveConfig(prompt="Look for failures.")}
    )
    responses = [
        MagicMock(stdout=_gh_list_response(0), returncode=0),
        MagicMock(returncode=0),
        MagicMock(stdout=_gh_create_response(), returncode=0),
    ]
    with patch("subprocess.run", side_effect=responses):
        result = source.fetch_task(_project(), **_fetch_defaults())  # type: ignore[arg-type]
    assert result is not None
    task, _ = result
    assert task.chosen_perspective == "red-team"
    assert task.perspective_prompt == "Look for failures."


def test_no_perspective_when_no_perspectives_loaded() -> None:
    source = _make_source(perspectives={})
    responses = [
        MagicMock(stdout=_gh_list_response(0), returncode=0),
        MagicMock(returncode=0),
        MagicMock(stdout=_gh_create_response(), returncode=0),
    ]
    with patch("subprocess.run", side_effect=responses):
        result = source.fetch_task(_project(), **_fetch_defaults())  # type: ignore[arg-type]
    assert result is not None
    task, _ = result
    assert task.chosen_perspective is None
    assert task.perspective_prompt is None


def test_source_perspectives_list_restricts_candidates() -> None:
    """When source.perspectives = ["red-team"], only red-team is eligible."""
    persp = {
        "red-team": PerspectiveConfig(prompt="Red."),
        "pre-mortem": PerspectiveConfig(prompt="Pre."),
    }
    source = _make_source(
        source_cfg=_source_cfg(perspectives=["red-team"]),
        perspectives=persp,
    )
    responses = [
        MagicMock(stdout=_gh_list_response(0), returncode=0),
        MagicMock(returncode=0),
        MagicMock(stdout=_gh_create_response(), returncode=0),
    ]
    with patch("subprocess.run", side_effect=responses):
        result = source.fetch_task(_project(), **_fetch_defaults())  # type: ignore[arg-type]
    assert result is not None
    task, _ = result
    assert task.chosen_perspective == "red-team"


# ── Issue creation ─────────────────────────────────────────────────────────────


def test_task_has_correct_item_fields() -> None:
    source = _make_source(perspectives={})
    responses = [
        MagicMock(stdout=_gh_list_response(0), returncode=0),
        MagicMock(returncode=0),
        MagicMock(stdout=_gh_create_response(number=42, repo="org/repo"), returncode=0),
    ]
    with patch("subprocess.run", side_effect=responses):
        result = source.fetch_task(_project(repo="org/repo"), **_fetch_defaults())  # type: ignore[arg-type]
    assert result is not None
    task, _ = result
    assert task.source == "proactive-improvement"
    assert task.item_type == "issue"
    assert task.item_number == 42
    assert task.item_url == "https://github.com/org/repo/issues/42"
    assert task.repo == "org/repo"
    assert task.source_label is None
    assert task.done_label is None


def test_issue_create_failure_returns_none() -> None:
    source = _make_source(perspectives={})
    responses = [
        MagicMock(stdout=_gh_list_response(0), returncode=0),  # cap check OK
        MagicMock(returncode=0),  # ensure label
        CalledProcessError(1, "gh"),  # issue create fails
    ]
    with patch("subprocess.run", side_effect=responses):
        result = source.fetch_task(_project(), **_fetch_defaults())  # type: ignore[arg-type]
    assert result is None


def test_permitted_actions_default_to_comment_and_open_pr() -> None:
    source = _make_source(perspectives={})
    responses = [
        MagicMock(stdout=_gh_list_response(0), returncode=0),
        MagicMock(returncode=0),
        MagicMock(stdout=_gh_create_response(), returncode=0),
    ]
    with patch("subprocess.run", side_effect=responses):
        result = source.fetch_task(_project(), **_fetch_defaults())  # type: ignore[arg-type]
    assert result is not None
    task, _ = result
    assert PermittedAction.COMMENT_ON_ISSUE in task.permitted_actions
    assert PermittedAction.OPEN_PR in task.permitted_actions
