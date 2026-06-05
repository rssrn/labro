"""Tests for GhLabelTaskSource (label_rules).

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from labro.config.schema import (
    DefaultsConfig,
    DigestConfig,
    LabelRule,
    LabroConfig,
    PermittedAction,
    ProjectConfig,
)
from labro.config.schema import (
    GhLabelSource as GhLabelSourceConfig,
)
from labro.task_sources.gh_label import GhLabelTaskSource

# ── Helpers ────────────────────────────────────────────────────────────────────


def _label_rule(
    label: str = "ai-dev",
    done_label: str = "ai-dev-done",
) -> LabelRule:
    return LabelRule(label=label, done_label=done_label)


def _source_config(
    label_rules: list[LabelRule] | None = None,
    permitted_actions: list[PermittedAction] | None = None,
    model: str | None = None,
) -> GhLabelSourceConfig:
    return GhLabelSourceConfig(
        type="gh-label",
        label_rules=label_rules or [_label_rule()],
        permitted_actions=permitted_actions,
        model=model,
    )


def _project(
    source_cfg: GhLabelSourceConfig | None = None,
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
    source: GhLabelTaskSource,
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

_LABEL_ITEM: dict[str, Any] = {
    "number": 42,
    "title": "Fix something",
    "body": "Some body.",
    "html_url": "https://github.com/org/repo/issues/42",
    "state": "open",
    "created_at": "2024-01-15T10:00:00Z",
    "user": {"login": "alice"},
    "labels": [{"name": "ai-dev"}],
    "assignees": [],
}


def test_label_rule_fetch_eligible() -> None:
    """An item carrying the configured label with no blocking labels is returned."""
    src_cfg = _source_config(label_rules=[_label_rule()])
    proj = _project(source_cfg=src_cfg)
    cfg = _config(proj)
    source = GhLabelTaskSource(src_cfg)

    def fake_gh_api(url: str) -> list[Any]:
        if "comments" in url:
            return []
        return [_LABEL_ITEM]

    with patch("labro.task_sources.gh_label._run_gh_api", side_effect=fake_gh_api):
        result = _fetch(source, proj, cfg)

    assert result is not None
    task, _agent_cfg = result
    assert task.item_number == 42
    assert task.item_type == "issue"
    assert task.source == "gh-label"
    assert task.source_label == "ai-dev"
    assert task.repo == "org/repo"


def test_label_rule_skip_done_label() -> None:
    """Items carrying the done label are excluded."""
    src_cfg = _source_config(label_rules=[_label_rule(done_label="ai-dev-done")])
    proj = _project(source_cfg=src_cfg)
    cfg = _config(proj)
    source = GhLabelTaskSource(src_cfg)

    done_item = {**_LABEL_ITEM, "labels": [{"name": "ai-dev"}, {"name": "ai-dev-done"}]}
    with patch("labro.task_sources.gh_label._run_gh_api", return_value=[done_item]):
        result = _fetch(source, proj, cfg)

    assert result is None


def test_label_rule_skip_ai_failed() -> None:
    """Items with the ``ai-failed`` label are excluded."""
    src_cfg = _source_config(label_rules=[_label_rule()])
    proj = _project(source_cfg=src_cfg)
    cfg = _config(proj)
    source = GhLabelTaskSource(src_cfg)

    failed_item = {**_LABEL_ITEM, "labels": [{"name": "ai-dev"}, {"name": "ai-failed"}]}
    with patch("labro.task_sources.gh_label._run_gh_api", return_value=[failed_item]):
        result = _fetch(source, proj, cfg)

    assert result is None


def test_label_rule_skip_ai_handover() -> None:
    """Items with the ``ai-handover`` label are excluded."""
    src_cfg = _source_config(label_rules=[_label_rule()])
    proj = _project(source_cfg=src_cfg)
    cfg = _config(proj)
    source = GhLabelTaskSource(src_cfg)

    handover_item = {**_LABEL_ITEM, "labels": [{"name": "ai-dev"}, {"name": "ai-handover"}]}
    with patch("labro.task_sources.gh_label._run_gh_api", return_value=[handover_item]):
        result = _fetch(source, proj, cfg)

    assert result is None


def test_label_rule_source_label_set() -> None:
    """source_label is populated with the matched label name."""
    src_cfg = _source_config(label_rules=[_label_rule(label="ai-dev", done_label="ai-dev-done")])
    proj = _project(source_cfg=src_cfg)
    cfg = _config(proj)
    source = GhLabelTaskSource(src_cfg)

    def fake_gh_api(url: str) -> list[Any]:
        if "comments" in url:
            return []
        return [_LABEL_ITEM]

    with patch("labro.task_sources.gh_label._run_gh_api", side_effect=fake_gh_api):
        result = _fetch(source, proj, cfg)

    assert result is not None
    task, _ = result
    assert task.source_label == "ai-dev"
    assert task.done_label == "ai-dev-done"


def test_label_rule_oldest_wins() -> None:
    """When multiple label_rules have candidates, the globally oldest item wins."""
    rule_a = _label_rule(label="ai-dev", done_label="ai-dev-done")
    rule_b = _label_rule(label="ai-ba", done_label="ai-ba-done")
    src_cfg = _source_config(label_rules=[rule_a, rule_b])
    proj = _project(source_cfg=src_cfg)
    cfg = _config(proj)
    source = GhLabelTaskSource(src_cfg)

    item_a: dict[str, Any] = {
        **_LABEL_ITEM,
        "number": 10,
        "created_at": "2024-03-01T00:00:00Z",
        "labels": [{"name": "ai-dev"}],
    }
    item_b: dict[str, Any] = {
        **_LABEL_ITEM,
        "number": 5,
        "created_at": "2024-01-01T00:00:00Z",
        "labels": [{"name": "ai-ba"}],
    }

    call_count = 0

    def fake_gh_api(url: str) -> list[Any]:
        nonlocal call_count
        if "comments" in url:
            return []
        call_count += 1
        return [item_a] if call_count == 1 else [item_b]

    with patch("labro.task_sources.gh_label._run_gh_api", side_effect=fake_gh_api):
        result = _fetch(source, proj, cfg)

    assert result is not None
    task, _ = result
    assert task.item_number == 5  # item_b is older
    assert task.source_label == "ai-ba"


def test_label_rule_model_override() -> None:
    """Label rule with its own model overrides source/project/defaults model."""
    rule = LabelRule(
        label="ai-dev",
        done_label="ai-dev-done",
        model="claude-code:anthropic/claude-haiku-4-5",
    )
    src_cfg = _source_config(label_rules=[rule], model="claude-code:anthropic/claude-sonnet-4-6")
    proj = _project(source_cfg=src_cfg)
    cfg = _config(proj)
    source = GhLabelTaskSource(src_cfg)

    def fake_gh_api(url: str) -> list[Any]:
        if "comments" in url:
            return []
        return [_LABEL_ITEM]

    with patch("labro.task_sources.gh_label._run_gh_api", side_effect=fake_gh_api):
        result = _fetch(source, proj, cfg)

    assert result is not None
    _, agent_cfg = result
    assert agent_cfg.slug == "claude-code:anthropic/claude-haiku-4-5"
    assert agent_cfg.model == "claude-haiku-4-5"
