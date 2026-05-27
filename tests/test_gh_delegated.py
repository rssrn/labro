"""Tests for actor_rules support in GhDelegatedTaskSource (M2 scope).

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from labro.config.schema import (
    ActorRule,
    DefaultsConfig,
    DigestConfig,
    LabelRule,
    LabroConfig,
    PermittedAction,
    ProjectConfig,
)
from labro.config.schema import (
    GhDelegatedSource as GhDelegatedSourceConfig,
)
from labro.task_sources.gh_delegated import GhDelegatedTaskSource

# ── Shared fixture data ────────────────────────────────────────────────────────

_ACTOR = "dependabot[bot]"
_DONE_LABEL = "dependencies-merged"

# A minimal open PR created by the actor with no blocking labels.
_ACTOR_ITEM: dict[str, Any] = {
    "number": 100,
    "title": "Bump some-dep from 1.0 to 2.0",
    "body": "Automated dependency bump.",
    "html_url": "https://github.com/org/repo/pull/100",
    "state": "open",
    "created_at": "2024-03-01T10:00:00Z",
    "user": {"login": _ACTOR},
    "labels": [],
    "pull_request": {"url": "https://api.github.com/repos/org/repo/pulls/100"},
}

# An item from a different actor (should always be excluded).
_OTHER_ACTOR_ITEM: dict[str, Any] = {
    "number": 101,
    "title": "Some other PR",
    "body": "",
    "html_url": "https://github.com/org/repo/pull/101",
    "state": "open",
    "created_at": "2024-02-01T10:00:00Z",
    "user": {"login": "someone-else"},
    "labels": [],
    "pull_request": {"url": "https://api.github.com/repos/org/repo/pulls/101"},
}

# Actor item that already has the done label.
_ACTOR_ITEM_DONE: dict[str, Any] = {
    **_ACTOR_ITEM,
    "number": 200,
    "labels": [{"name": _DONE_LABEL}],
}

# Actor item that has ai-failed.
_ACTOR_ITEM_AI_FAILED: dict[str, Any] = {
    **_ACTOR_ITEM,
    "number": 201,
    "labels": [{"name": "ai-failed"}],
}


# ── Helpers ────────────────────────────────────────────────────────────────────


def _actor_rule(
    actor: str = _ACTOR,
    done_label: str = _DONE_LABEL,
    model: str | None = None,
    permitted_actions: list[PermittedAction] | None = None,
) -> ActorRule:
    return ActorRule(
        actor=actor,
        done_label=done_label,
        model=model,
        permitted_actions=permitted_actions,
    )


def _label_rule(
    label: str = "ai-dev",
    done_label: str = "ai-dev-done",
) -> LabelRule:
    return LabelRule(label=label, done_label=done_label)


def _source_config(
    label_rules: list[LabelRule] | None = None,
    actor_rules: list[ActorRule] | None = None,
    permitted_actions: list[PermittedAction] | None = None,
    model: str | None = None,
) -> GhDelegatedSourceConfig:
    return GhDelegatedSourceConfig(
        type="gh-delegated",
        label_rules=label_rules or [],
        actor_rules=actor_rules or [_actor_rule()],
        permitted_actions=permitted_actions,
        model=model,
    )


def _project(
    source_cfg: GhDelegatedSourceConfig | None = None,
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
        defaults=DefaultsConfig(model="claude-opus-4-7", max_turns=20, timeout_s=600),
        projects=[project or _project()],
    )


def _fetch(
    source: GhDelegatedTaskSource,
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


def _comments_mock(url: str) -> list[Any]:
    """Side-effect: return empty list for comment URLs, raise for unexpected ones."""
    if "comments" in url:
        return []
    raise AssertionError(f"Unexpected _run_gh_api call: {url}")


# ── Tests ──────────────────────────────────────────────────────────────────────


def test_actor_rule_fetch_eligible() -> None:
    """An item by the configured actor with no blocking labels is returned."""
    src_cfg = _source_config(actor_rules=[_actor_rule()])
    proj = _project(source_cfg=src_cfg)
    cfg = _config(proj)
    source = GhDelegatedTaskSource(src_cfg)

    all_open = [_ACTOR_ITEM, _OTHER_ACTOR_ITEM]

    def fake_gh_api(url: str) -> list[Any]:
        if "comments" in url:
            return []
        return all_open

    with patch("labro.task_sources.gh_delegated._run_gh_api", side_effect=fake_gh_api):
        result = _fetch(source, proj, cfg)

    assert result is not None
    task, _agent_cfg = result
    assert task.item_number == 100
    assert task.item_type == "pr"
    assert task.source == "gh-delegated"
    assert task.repo == "org/repo"


def test_actor_rule_skip_done_label() -> None:
    """Items carrying the done label are excluded; no result when only that item exists."""
    src_cfg = _source_config(actor_rules=[_actor_rule(done_label=_DONE_LABEL)])
    proj = _project(source_cfg=src_cfg)
    cfg = _config(proj)
    source = GhDelegatedTaskSource(src_cfg)

    all_open = [_ACTOR_ITEM_DONE]

    with patch("labro.task_sources.gh_delegated._run_gh_api", return_value=all_open):
        result = _fetch(source, proj, cfg)

    assert result is None


def test_actor_rule_skip_ai_failed() -> None:
    """Items with the ``ai-failed`` label are excluded."""
    src_cfg = _source_config(actor_rules=[_actor_rule()])
    proj = _project(source_cfg=src_cfg)
    cfg = _config(proj)
    source = GhDelegatedTaskSource(src_cfg)

    all_open = [_ACTOR_ITEM_AI_FAILED]

    with patch("labro.task_sources.gh_delegated._run_gh_api", return_value=all_open):
        result = _fetch(source, proj, cfg)

    assert result is None


def test_actor_rule_source_label_is_none() -> None:
    """Actor-rule items have source_label=None (no label to remove on success)."""
    src_cfg = _source_config(actor_rules=[_actor_rule()])
    proj = _project(source_cfg=src_cfg)
    cfg = _config(proj)
    source = GhDelegatedTaskSource(src_cfg)

    def fake_gh_api(url: str) -> list[Any]:
        if "comments" in url:
            return []
        return [_ACTOR_ITEM]

    with patch("labro.task_sources.gh_delegated._run_gh_api", side_effect=fake_gh_api):
        result = _fetch(source, proj, cfg)

    assert result is not None
    task, _ = result
    assert task.source_label is None
    assert task.done_label == _DONE_LABEL


def test_label_and_actor_candidates_pooled() -> None:
    """Candidates from label_rules and actor_rules are pooled; the oldest wins.

    Label-rule item #42 created 2024-01-15 is older than actor-rule item #100
    created 2024-03-01, so #42 should be selected.
    """
    label_rule = _label_rule(label="ai-dev", done_label="ai-dev-done")
    actor_rule_cfg = _actor_rule()
    src_cfg = GhDelegatedSourceConfig(
        type="gh-delegated",
        label_rules=[label_rule],
        actor_rules=[actor_rule_cfg],
        permitted_actions=[PermittedAction.COMMENT_ON_ISSUE],
    )
    proj = _project(source_cfg=src_cfg)
    cfg = _config(proj)
    source = GhDelegatedTaskSource(src_cfg)

    label_item: dict[str, Any] = {
        "number": 42,
        "title": "Fix something",
        "body": "",
        "html_url": "https://github.com/org/repo/issues/42",
        "state": "open",
        "created_at": "2024-01-15T10:00:00Z",
        "user": {"login": "alice"},
        "labels": [{"name": "ai-dev"}],
    }

    call_count = 0

    def fake_gh_api(url: str) -> list[Any]:
        nonlocal call_count
        if "comments" in url:
            return []
        call_count += 1
        # First call: label_rules fetch (returns label_item)
        # Second call: actor_rules all-open fetch (returns both)
        if call_count == 1:
            return [label_item]
        return [label_item, _ACTOR_ITEM]

    with patch("labro.task_sources.gh_delegated._run_gh_api", side_effect=fake_gh_api):
        result = _fetch(source, proj, cfg)

    assert result is not None
    task, _ = result
    assert task.item_number == 42  # oldest across both pools
    assert task.source_label == "ai-dev"  # label_rule → source_label set


def test_actor_rule_model_override() -> None:
    """Actor rule with its own model overrides source/project/defaults model."""
    rule = _actor_rule(model="claude-haiku-4-5")
    src_cfg = _source_config(actor_rules=[rule], model="claude-sonnet-4-6")
    proj = _project(source_cfg=src_cfg)
    cfg = _config(proj)
    source = GhDelegatedTaskSource(src_cfg)

    def fake_gh_api(url: str) -> list[Any]:
        if "comments" in url:
            return []
        return [_ACTOR_ITEM]

    with patch("labro.task_sources.gh_delegated._run_gh_api", side_effect=fake_gh_api):
        result = _fetch(source, proj, cfg)

    assert result is not None
    _, agent_cfg = result
    assert agent_cfg.model == "claude-haiku-4-5"
