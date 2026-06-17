"""Tests for task_sources/gh_dependabot_alert.py.

Covers:
- No cap: many existing tracking issues do not block the source
- No unfixed alerts: source returns None when all alerts have fixed_at set
- No unaddressed alerts: source returns None when all alerts have tracking issues
- API failure: source returns None when gh api call fails
- Issue creation: returned Task has correct item_type, item_number, item_url
- Severity ordering: critical alerts picked before low
- Closed-issue dedup: recently closed blocks re-creation; old closed does not

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from subprocess import CalledProcessError
from typing import Any
from unittest.mock import MagicMock, patch

from labro.config.schema import (
    DependabotAlertSource as DependabotAlertSourceConfig,
)
from labro.config.schema import (
    PermittedAction,
    ProjectConfig,
)
from labro.task_sources.gh_dependabot_alert import DependabotAlertTaskSource

# ── Fixtures ────────────────────────────────────────────────────────────────────

_ALERT_WITH_FIX = {
    "state": "fixed",
    "fixed_at": "2025-01-01T00:00:00Z",
    "dependency": {
        "package": {"name": "lodash"},
        "manifest_path": "package-lock.json",
    },
    "security_advisory": {
        "ghsa_id": "GHSA-xxxx-xxxx-xxxx",
        "summary": "Prototype pollution in lodash",
        "severity": "high",
        "cve_id": "CVE-2025-0001",
    },
}

_ALERT_CRITICAL = {
    "state": "open",
    "fixed_at": None,
    "dependency": {
        "package": {"name": "minimist"},
        "manifest_path": "package-lock.json",
    },
    "security_advisory": {
        "ghsa_id": "GHSA-aaaa-bbbb-cccc",
        "summary": "Prototype pollution in minimist",
        "description": "A crafted payload can pollute the prototype.",
        "severity": "critical",
        "cve_id": "CVE-2025-0002",
    },
    "security_vulnerability": {
        "vulnerable_version_range": "< 1.2.6",
        "patched_versions": ">= 1.2.6",
    },
}

_ALERT_HIGH = {
    "state": "open",
    "fixed_at": None,
    "dependency": {
        "package": {"name": "lodash"},
        "manifest_path": "package-lock.json",
    },
    "security_advisory": {
        "ghsa_id": "GHSA-xxxx-yyyy-zzzz",
        "summary": "Prototype pollution in lodash",
        "severity": "high",
    },
}

_ALERT_LOW = {
    "state": "open",
    "fixed_at": None,
    "dependency": {
        "package": {"name": "debug"},
        "manifest_path": "package-lock.json",
    },
    "security_advisory": {
        "ghsa_id": "GHSA-dddd-eeee-ffff",
        "summary": "ReDoS in debug",
        "severity": "low",
    },
}


def _project(repo: str = "org/repo") -> ProjectConfig:
    return ProjectConfig(
        name="test-proj",
        repo=repo,
        cron="0 * * * *",
        model=["claude-code:anthropic/claude-sonnet-4-6"],
    )


def _source_cfg(**kwargs: object) -> DependabotAlertSourceConfig:
    defaults: dict[str, object] = {
        "type": "gh-dependabot-alert",
    }
    defaults.update(kwargs)
    return DependabotAlertSourceConfig(**defaults)  # type: ignore[arg-type]  # dict[str, object] vs typed kwargs


def _make_source(
    source_cfg: DependabotAlertSourceConfig | None = None,
) -> DependabotAlertTaskSource:
    return DependabotAlertTaskSource(
        source_config=source_cfg or _source_cfg(),
        personas={},
    )


def _fetch_defaults() -> dict[str, object]:
    return {
        "defaults_model": ["claude-code:anthropic/claude-sonnet-4-6"],
        "defaults_max_turns": 20,
        "defaults_timeout_s": 600,
        "defaults_max_comments": 10,
    }


def _gh_list_response(items: list[Any]) -> str:
    return json.dumps(items)


def _gh_create_response(number: int = 99, repo: str = "org/repo") -> str:
    return f"https://github.com/{repo}/issues/{number}\n"


# ── No cap — many existing tracking issues do not block the source ─────────────


def test_many_existing_issues_do_not_block_when_untracked_alert_exists() -> None:
    """Source has no cap: many open tracking issues don't prevent a new one for a novel alert."""
    many_issues = [
        {"state": "open", "title": "Dependabot alert: other-pkg", "body": "GHSA-other"}
        for _ in range(10)
    ]
    responses = [
        MagicMock(stdout=_gh_list_response([_ALERT_CRITICAL]), returncode=0),  # fetch alerts
        MagicMock(stdout=_gh_list_response(many_issues), returncode=0),  # fetch existing issues
        MagicMock(returncode=0),  # ensure label
        MagicMock(stdout=_gh_create_response(42), returncode=0),  # issue create
    ]
    source = _make_source()
    with patch("subprocess.run", side_effect=responses):
        result = source.fetch_task(_project(), **_fetch_defaults())  # type: ignore[arg-type]  # dict[str, object] vs typed kwargs
    assert result is not None


# ── Alert fetching ─────────────────────────────────────────────────────────────


def test_no_unfixed_alerts_returns_none() -> None:
    """When all alerts are already fixed (fixed_at set), source returns None."""
    responses = [
        MagicMock(stdout=_gh_list_response([_ALERT_WITH_FIX]), returncode=0),  # alerts — fixed
    ]
    source = _make_source()
    with patch("subprocess.run", side_effect=responses):
        result = source.fetch_task(_project(), **_fetch_defaults())  # type: ignore[arg-type]  # dict[str, object] vs typed kwargs
    assert result is None


def test_alerts_fetch_failure_returns_none() -> None:
    """When gh api call for alerts fails, source returns None."""
    responses = [
        CalledProcessError(1, "gh"),  # fetch alerts fails
    ]
    source = _make_source()
    with patch("subprocess.run", side_effect=responses):
        result = source.fetch_task(_project(), **_fetch_defaults())  # type: ignore[arg-type]  # dict[str, object] vs typed kwargs
    assert result is None


def test_fetch_existing_issues_failure_returns_none() -> None:
    """When fetching existing tracking issues fails, source returns None."""
    responses = [
        MagicMock(stdout=_gh_list_response([_ALERT_CRITICAL]), returncode=0),  # fetch alerts
        CalledProcessError(1, "gh"),  # fetch existing issues fails
    ]
    source = _make_source()
    with patch("subprocess.run", side_effect=responses):
        result = source.fetch_task(_project(), **_fetch_defaults())  # type: ignore[arg-type]  # dict[str, object] vs typed kwargs
    assert result is None


# ── Dedup ──────────────────────────────────────────────────────────────────────


def test_all_alerts_already_have_tracking_issues_returns_none() -> None:
    """When every alert already has a tracking issue, source returns None."""
    existing_issue = {
        "state": "open",
        "title": "Dependabot alert: minimist (GHSA-aaaa-bbbb-cccc) [critical]",
        "body": (
            "<!-- Labro Dependabot alert — do not edit this header -->\n"
            "**GHSA:** `GHSA-aaaa-bbbb-cccc`"
        ),
    }
    responses = [
        MagicMock(stdout=_gh_list_response([_ALERT_CRITICAL]), returncode=0),  # fetch alerts
        MagicMock(stdout=_gh_list_response([existing_issue]), returncode=0),  # existing
    ]
    source = _make_source()
    with patch("subprocess.run", side_effect=responses):
        result = source.fetch_task(_project(), **_fetch_defaults())  # type: ignore[arg-type]  # dict[str, object] vs typed kwargs
    assert result is None


def test_closed_issue_within_10_days_blocks_recreation() -> None:
    """A closed issue with matching GHSA blocks re-creation when closed within 10 days."""
    recently_closed = (datetime.now(UTC) - timedelta(days=1)).isoformat().replace("+00:00", "Z")
    existing_issue = {
        "state": "closed",
        "closed_at": recently_closed,
        "title": "Dependabot alert: minimist (GHSA-aaaa-bbbb-cccc) [critical]",
        "body": (
            "<!-- Labro Dependabot alert — do not edit this header -->\n"
            "**GHSA:** `GHSA-aaaa-bbbb-cccc`"
        ),
    }
    responses = [
        MagicMock(stdout=_gh_list_response([_ALERT_CRITICAL]), returncode=0),  # fetch alerts
        MagicMock(stdout=_gh_list_response([existing_issue]), returncode=0),  # existing
    ]
    source = _make_source()
    with patch("subprocess.run", side_effect=responses):
        result = source.fetch_task(_project(), **_fetch_defaults())  # type: ignore[arg-type]
    assert result is None


def test_closed_issue_older_than_10_days_allows_recreation() -> None:
    """A closed issue older than 10 days does not block re-creation for the same alert."""
    old_closed = (datetime.now(UTC) - timedelta(days=30)).isoformat().replace("+00:00", "Z")
    existing_issue = {
        "state": "closed",
        "closed_at": old_closed,
        "title": "Dependabot alert: minimist (GHSA-aaaa-bbbb-cccc) [critical]",
        "body": (
            "<!-- Labro Dependabot alert — do not edit this header -->\n"
            "**GHSA:** `GHSA-aaaa-bbbb-cccc`"
        ),
    }
    responses = [
        MagicMock(stdout=_gh_list_response([_ALERT_CRITICAL]), returncode=0),  # fetch alerts
        MagicMock(stdout=_gh_list_response([existing_issue]), returncode=0),  # existing
        MagicMock(returncode=0),  # ensure label
        MagicMock(stdout=_gh_create_response(), returncode=0),  # issue create
    ]
    source = _make_source()
    with patch("subprocess.run", side_effect=responses):
        result = source.fetch_task(_project(), **_fetch_defaults())  # type: ignore[arg-type]
    assert result is not None


def test_closed_issue_missing_closed_at_does_not_block() -> None:
    """Closed issue without closed_at is treated as inactive — does not block re-creation."""
    existing_issue = {
        "state": "closed",
        # no closed_at key
        "title": "Dependabot alert: minimist (GHSA-aaaa-bbbb-cccc) [critical]",
        "body": (
            "<!-- Labro Dependabot alert — do not edit this header -->\n"
            "**GHSA:** `GHSA-aaaa-bbbb-cccc`"
        ),
    }
    responses = [
        MagicMock(stdout=_gh_list_response([_ALERT_CRITICAL]), returncode=0),  # fetch alerts
        MagicMock(stdout=_gh_list_response([existing_issue]), returncode=0),  # existing
        MagicMock(returncode=0),  # ensure label
        MagicMock(stdout=_gh_create_response(), returncode=0),  # issue create
    ]
    source = _make_source()
    with patch("subprocess.run", side_effect=responses):
        result = source.fetch_task(_project(), **_fetch_defaults())  # type: ignore[arg-type]
    assert result is not None


# ── Issue creation ─────────────────────────────────────────────────────────────


def test_task_has_correct_item_fields() -> None:
    """Returned Task has correct source, item_type, item_number, item_url, repo."""
    responses = [
        MagicMock(stdout=_gh_list_response([_ALERT_CRITICAL]), returncode=0),  # fetch alerts
        MagicMock(stdout=_gh_list_response([]), returncode=0),  # existing
        MagicMock(returncode=0),  # ensure label
        MagicMock(stdout=_gh_create_response(number=42, repo="org/repo"), returncode=0),  # create
    ]
    source = _make_source()
    with patch("subprocess.run", side_effect=responses):
        result = source.fetch_task(_project(repo="org/repo"), **_fetch_defaults())  # type: ignore[arg-type]  # dict[str, object] vs typed kwargs
    assert result is not None
    task, _ = result
    assert task.source == "gh-dependabot-alert"
    assert task.item_type == "issue"
    assert task.item_number == 42
    assert task.item_url == "https://github.com/org/repo/issues/42"
    assert task.repo == "org/repo"
    assert task.source_label is None
    assert task.done_label is None


def test_issue_create_failure_returns_none() -> None:
    """When gh issue create fails, source returns None."""
    responses = [
        MagicMock(stdout=_gh_list_response([_ALERT_CRITICAL]), returncode=0),  # fetch alerts
        MagicMock(stdout=_gh_list_response([]), returncode=0),  # existing
        MagicMock(returncode=0),  # ensure label
        CalledProcessError(1, "gh"),  # issue create fails
    ]
    source = _make_source()
    with patch("subprocess.run", side_effect=responses):
        result = source.fetch_task(_project(), **_fetch_defaults())  # type: ignore[arg-type]  # dict[str, object] vs typed kwargs
    assert result is None


def test_permitted_actions_default_to_comment_and_open_pr() -> None:
    """Default permitted_actions includes COMMENT_ON_ISSUE and OPEN_PR."""
    responses = [
        MagicMock(stdout=_gh_list_response([_ALERT_CRITICAL]), returncode=0),  # fetch alerts
        MagicMock(stdout=_gh_list_response([]), returncode=0),  # existing
        MagicMock(returncode=0),  # ensure label
        MagicMock(stdout=_gh_create_response(), returncode=0),  # issue create
    ]
    source = _make_source()
    with patch("subprocess.run", side_effect=responses):
        result = source.fetch_task(_project(), **_fetch_defaults())  # type: ignore[arg-type]  # dict[str, object] vs typed kwargs
    assert result is not None
    task, _ = result
    assert PermittedAction.COMMENT_ON_ISSUE in task.permitted_actions
    assert PermittedAction.OPEN_PR in task.permitted_actions


def test_source_description_includes_package_name() -> None:
    """source_description contains the alerted package name."""
    responses = [
        MagicMock(stdout=_gh_list_response([_ALERT_CRITICAL]), returncode=0),  # fetch alerts
        MagicMock(stdout=_gh_list_response([]), returncode=0),  # existing
        MagicMock(returncode=0),  # ensure label
        MagicMock(stdout=_gh_create_response(), returncode=0),  # issue create
    ]
    source = _make_source()
    with patch("subprocess.run", side_effect=responses):
        result = source.fetch_task(_project(), **_fetch_defaults())  # type: ignore[arg-type]  # dict[str, object] vs typed kwargs
    assert result is not None
    task, _ = result
    assert "minimist" in (task.source_description or "")


# ── Severity ordering ──────────────────────────────────────────────────────────


def test_critical_alert_picked_before_low() -> None:
    """When multiple unfixed alerts exist, the highest severity is picked first."""
    responses = [
        MagicMock(stdout=_gh_list_response([_ALERT_LOW, _ALERT_CRITICAL]), returncode=0),  # alerts
        MagicMock(stdout=_gh_list_response([]), returncode=0),  # existing
        MagicMock(returncode=0),  # ensure label
        MagicMock(stdout=_gh_create_response(), returncode=0),  # issue create
    ]
    source = _make_source()
    with patch("subprocess.run", side_effect=responses):
        result = source.fetch_task(_project(), **_fetch_defaults())  # type: ignore[arg-type]  # dict[str, object] vs typed kwargs
    assert result is not None
    task, _ = result
    assert "minimist" in (task.description or "")
    assert "critical" in (task.description or "")
