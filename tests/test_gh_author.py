"""Tests for GhAuthorTaskSource (author_rules).

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from labro.config.schema import (
    AuthorRule,
    DefaultsConfig,
    DigestConfig,
    LabroConfig,
    PermittedAction,
    ProjectConfig,
)
from labro.config.schema import (
    GhAuthorSource as GhAuthorSourceConfig,
)
from labro.task_sources.gh_author import GhAuthorTaskSource

# ── Shared fixture data ────────────────────────────────────────────────────────

_ACTOR = "dependabot[bot]"
_DONE_LABEL = "dependencies-merged"

_ACTOR_ITEM: dict[str, Any] = {
    "number": 100,
    "title": "Bump some-dep from 1.0 to 2.0",
    "body": "Automated dependency bump.",
    "html_url": "https://github.com/org/repo/pull/100",
    "state": "open",
    "created_at": "2024-03-01T10:00:00Z",
    "user": {"login": _ACTOR},
    "labels": [],
    "assignees": [],
    "pull_request": {"url": "https://api.github.com/repos/org/repo/pulls/100"},
}

_OTHER_ACTOR_ITEM: dict[str, Any] = {
    "number": 101,
    "title": "Some other PR",
    "body": "",
    "html_url": "https://github.com/org/repo/pull/101",
    "state": "open",
    "created_at": "2024-02-01T10:00:00Z",
    "user": {"login": "someone-else"},
    "labels": [],
    "assignees": [],
    "pull_request": {"url": "https://api.github.com/repos/org/repo/pulls/101"},
}

_ACTOR_ITEM_DONE: dict[str, Any] = {
    **_ACTOR_ITEM,
    "number": 200,
    "labels": [{"name": _DONE_LABEL}],
}

_ACTOR_ITEM_AI_FAILED: dict[str, Any] = {
    **_ACTOR_ITEM,
    "number": 201,
    "labels": [{"name": "ai-failed"}],
}

# ── Helpers ────────────────────────────────────────────────────────────────────


def _author_rule(
    actor: str = _ACTOR,
    done_label: str = _DONE_LABEL,
    model: str | None = None,
    permitted_actions: list[PermittedAction] | None = None,
    requires_dependabot_alert: bool = False,
) -> AuthorRule:
    return AuthorRule(
        actor=actor,
        done_label=done_label,
        model=model,
        permitted_actions=permitted_actions,
        requires_dependabot_alert=requires_dependabot_alert,
    )


def _source_config(
    author_rules: list[AuthorRule] | None = None,
    permitted_actions: list[PermittedAction] | None = None,
    model: str | None = None,
) -> GhAuthorSourceConfig:
    return GhAuthorSourceConfig(
        type="gh-author",
        author_rules=author_rules or [_author_rule()],
        permitted_actions=permitted_actions,
        model=model,
    )


def _project(
    source_cfg: GhAuthorSourceConfig | None = None,
    permitted_actions: list[PermittedAction] | None = None,
    model: str | None = None,
) -> ProjectConfig:
    return ProjectConfig(
        name="test-project",
        repo="org/repo",
        cron="0 * * * *",
        task_sources=[source_cfg or _source_config()],
        permitted_actions=permitted_actions,
        model=model,
    )


def _config(project: ProjectConfig | None = None) -> LabroConfig:
    return LabroConfig(
        digest=DigestConfig(enabled=False),
        defaults=DefaultsConfig(
            model="claude-code:anthropic/claude-opus-4-7", max_turns=20, timeout_s=600
        ),
        projects=[project or _project()],
    )


def _fetch(
    source: GhAuthorTaskSource,
    project: ProjectConfig,
    cfg: LabroConfig,
) -> Any:
    return source.fetch_task(
        project=project,
        defaults_model=cfg.defaults.model,
        defaults_max_turns=cfg.defaults.max_turns,
        defaults_timeout_s=cfg.defaults.timeout_s,
        defaults_max_comments=cfg.defaults.max_comments,
    )


# ── Tests ──────────────────────────────────────────────────────────────────────


def test_author_rule_fetch_eligible() -> None:
    """An item by the configured author with no blocking labels is returned."""
    src_cfg = _source_config(author_rules=[_author_rule()])
    proj = _project(source_cfg=src_cfg)
    cfg = _config(proj)
    source = GhAuthorTaskSource(src_cfg)

    all_open = [_ACTOR_ITEM, _OTHER_ACTOR_ITEM]

    def fake_gh_api(url: str) -> list[Any]:
        if "comments" in url:
            return []
        return all_open

    with patch("labro.task_sources.gh_author._run_gh_api", side_effect=fake_gh_api):
        result = _fetch(source, proj, cfg)

    assert result is not None
    task, _agent_cfg = result
    assert task.item_number == 100
    assert task.item_type == "pr"
    assert task.source == "gh-author"
    assert task.source_label is None
    assert task.repo == "org/repo"


def test_author_rule_skip_done_label() -> None:
    """Items carrying the done label are excluded."""
    src_cfg = _source_config(author_rules=[_author_rule(done_label=_DONE_LABEL)])
    proj = _project(source_cfg=src_cfg)
    cfg = _config(proj)
    source = GhAuthorTaskSource(src_cfg)

    with patch("labro.task_sources.gh_author._run_gh_api", return_value=[_ACTOR_ITEM_DONE]):
        result = _fetch(source, proj, cfg)

    assert result is None


def test_author_rule_skip_ai_failed() -> None:
    """Items with the ``ai-failed`` label are excluded."""
    src_cfg = _source_config(author_rules=[_author_rule()])
    proj = _project(source_cfg=src_cfg)
    cfg = _config(proj)
    source = GhAuthorTaskSource(src_cfg)

    with patch("labro.task_sources.gh_author._run_gh_api", return_value=[_ACTOR_ITEM_AI_FAILED]):
        result = _fetch(source, proj, cfg)

    assert result is None


def test_author_rule_skip_ai_handover() -> None:
    """Items with the ``ai-handover`` label are excluded."""
    src_cfg = _source_config(author_rules=[_author_rule()])
    proj = _project(source_cfg=src_cfg)
    cfg = _config(proj)
    source = GhAuthorTaskSource(src_cfg)

    handover_item = {**_ACTOR_ITEM, "number": 202, "labels": [{"name": "ai-handover"}]}
    with patch("labro.task_sources.gh_author._run_gh_api", return_value=[handover_item]):
        result = _fetch(source, proj, cfg)

    assert result is None


def test_author_rule_source_label_is_none() -> None:
    """Author-rule items always have source_label=None (no label to remove on success)."""
    src_cfg = _source_config(author_rules=[_author_rule()])
    proj = _project(source_cfg=src_cfg)
    cfg = _config(proj)
    source = GhAuthorTaskSource(src_cfg)

    def fake_gh_api(url: str) -> list[Any]:
        if "comments" in url:
            return []
        return [_ACTOR_ITEM]

    with patch("labro.task_sources.gh_author._run_gh_api", side_effect=fake_gh_api):
        result = _fetch(source, proj, cfg)

    assert result is not None
    task, _ = result
    assert task.source_label is None
    assert task.done_label == _DONE_LABEL


def test_author_rule_model_override() -> None:
    """Author rule with its own model overrides source/project/defaults model."""
    rule = _author_rule(model="claude-code:anthropic/claude-haiku-4-5")
    src_cfg = _source_config(author_rules=[rule], model="claude-code:anthropic/claude-sonnet-4-6")
    proj = _project(source_cfg=src_cfg)
    cfg = _config(proj)
    source = GhAuthorTaskSource(src_cfg)

    def fake_gh_api(url: str) -> list[Any]:
        if "comments" in url:
            return []
        return [_ACTOR_ITEM]

    with patch("labro.task_sources.gh_author._run_gh_api", side_effect=fake_gh_api):
        result = _fetch(source, proj, cfg)

    assert result is not None
    _, agent_cfg = result
    assert agent_cfg.slug == "claude-code:anthropic/claude-haiku-4-5"
    assert agent_cfg.model == "claude-haiku-4-5"


def _alert(pkg: str, manifest: str = "dashboard/package-lock.json") -> dict[str, Any]:
    """A single open Dependabot alert as returned by the alerts API."""
    return {
        "state": "open",
        "dependency": {"package": {"name": pkg}, "manifest_path": manifest},
        "security_advisory": {"severity": "medium"},
    }


def test_author_rule_requires_dependabot_alert_match() -> None:
    """A PR bumping a package with an open Dependabot alert is eligible."""
    rule = _author_rule(requires_dependabot_alert=True)
    src_cfg = _source_config(author_rules=[rule])
    proj = _project(source_cfg=src_cfg)
    cfg = _config(proj)
    source = GhAuthorTaskSource(src_cfg)

    security_pr = {**_ACTOR_ITEM, "body": "Bumps [vite] from 5.4.21 to 8.0.16 in /dashboard"}

    def fake_gh_api(url: str) -> list[Any]:
        if "comments" in url:
            return []
        if "dependabot/alerts" in url:
            return [_alert("vite")]
        return [security_pr]

    with patch("labro.task_sources.gh_author._run_gh_api", side_effect=fake_gh_api):
        result = _fetch(source, proj, cfg)

    assert result is not None
    task, _ = result
    assert task.item_number == 100


def test_author_rule_requires_dependabot_alert_no_match() -> None:
    """A routine bump with no corresponding open alert is skipped."""
    rule = _author_rule(requires_dependabot_alert=True)
    src_cfg = _source_config(author_rules=[rule])
    proj = _project(source_cfg=src_cfg)
    cfg = _config(proj)
    source = GhAuthorTaskSource(src_cfg)

    routine_pr = {**_ACTOR_ITEM, "body": "Bumps [left-pad] from 1.0 to 1.1 in /dashboard"}

    def fake_gh_api(url: str) -> list[Any]:
        if "comments" in url:
            return []
        if "dependabot/alerts" in url:
            return [_alert("vite")]  # alert is for a different package
        return [routine_pr]

    with patch("labro.task_sources.gh_author._run_gh_api", side_effect=fake_gh_api):
        result = _fetch(source, proj, cfg)

    assert result is None


def test_author_rule_requires_dependabot_alert_manifest_dir_scoped() -> None:
    """A bump of the alerted package in a *different* directory is not matched."""
    rule = _author_rule(requires_dependabot_alert=True)
    src_cfg = _source_config(author_rules=[rule])
    proj = _project(source_cfg=src_cfg)
    cfg = _config(proj)
    source = GhAuthorTaskSource(src_cfg)

    other_dir_pr = {**_ACTOR_ITEM, "body": "Bumps [vite] from 5.4.21 to 8.0.16 in /frontend"}

    def fake_gh_api(url: str) -> list[Any]:
        if "comments" in url:
            return []
        if "dependabot/alerts" in url:
            return [_alert("vite", manifest="dashboard/package-lock.json")]
        return [other_dir_pr]

    with patch("labro.task_sources.gh_author._run_gh_api", side_effect=fake_gh_api):
        result = _fetch(source, proj, cfg)

    assert result is None


def test_author_rule_requires_dependabot_alert_api_failure_skips() -> None:
    """If the alerts API errors (e.g. alerts disabled), the rule matches nothing."""
    rule = _author_rule(requires_dependabot_alert=True)
    src_cfg = _source_config(author_rules=[rule])
    proj = _project(source_cfg=src_cfg)
    cfg = _config(proj)
    source = GhAuthorTaskSource(src_cfg)

    def fake_gh_api(url: str) -> list[Any]:
        if "comments" in url:
            return []
        if "dependabot/alerts" in url:
            raise RuntimeError("403 Dependabot alerts are disabled for this repository")
        return [{**_ACTOR_ITEM, "body": "Bumps [vite] from 5.4.21 to 8.0.16 in /dashboard"}]

    with patch("labro.task_sources.gh_author._run_gh_api", side_effect=fake_gh_api):
        result = _fetch(source, proj, cfg)

    assert result is None


def test_author_rule_multiple_authors_oldest_wins() -> None:
    """When multiple author_rules match, the globally oldest item wins."""
    rule_a = _author_rule(actor="dependabot[bot]", done_label="dep-done")
    rule_b = _author_rule(actor="renovate[bot]", done_label="renovate-done")
    src_cfg = _source_config(author_rules=[rule_a, rule_b])
    proj = _project(source_cfg=src_cfg)
    cfg = _config(proj)
    source = GhAuthorTaskSource(src_cfg)

    renovate_item: dict[str, Any] = {
        **_ACTOR_ITEM,
        "number": 5,
        "created_at": "2024-01-01T00:00:00Z",
        "user": {"login": "renovate[bot]"},
    }

    def fake_gh_api(url: str) -> list[Any]:
        if "comments" in url:
            return []
        return [_ACTOR_ITEM, renovate_item]

    with patch("labro.task_sources.gh_author._run_gh_api", side_effect=fake_gh_api):
        result = _fetch(source, proj, cfg)

    assert result is not None
    task, _ = result
    assert task.item_number == 5  # renovate_item is older
