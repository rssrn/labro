"""Tests for picker.py and task_sources/gh_label.py.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

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
from labro.models import AgentConfig, Task
from labro.picker import pick
from labro.task_sources.gh_label import (
    GhLabelTaskSource,
    _item_type,
    _label_names,
    _resolve_model_slug,
    _resolve_permitted_actions,
)

# ── gh API mock helper ─────────────────────────────────────────────────────────


def gh_api_mock(issues_fixture: list[Any]) -> Callable[[str], list[Any]]:
    """Return a ``_run_gh_api`` side_effect that serves *issues_fixture* for
    issue-list calls and an empty list for comments calls."""

    def _side_effect(url: str) -> list[Any]:
        if "comments" in url:
            return []
        return issues_fixture

    return _side_effect


# ── fixture helpers ────────────────────────────────────────────────────────────

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


# ── shared project/config builders ────────────────────────────────────────────


def _label_rule(
    label: str = "ai-dev",
    done_label: str = "ai-dev-done",
    permitted_actions: list[PermittedAction] | None = None,
) -> LabelRule:
    return LabelRule(label=label, done_label=done_label, permitted_actions=permitted_actions)


def _source_config(
    rules: list[LabelRule] | None = None,
    permitted_actions: list[PermittedAction] | None = None,
    model: str | None = None,
) -> GhLabelSourceConfig:
    return GhLabelSourceConfig(
        type="gh-label",
        label_rules=rules or [_label_rule()],
        permitted_actions=permitted_actions,
        model=model,
    )


def _project(
    source_cfg: GhLabelSourceConfig | None = None,
    permitted_actions: list[PermittedAction] | None = None,
    model: str | None = None,
    max_turns: int | None = None,
    timeout_s: int | None = None,
) -> ProjectConfig:
    src = source_cfg or _source_config()
    return ProjectConfig(
        name="test-project",
        repo="org/repo",
        cron="0 * * * *",
        task_sources=[src],
        permitted_actions=permitted_actions,
        model=model,
        max_turns=max_turns,
        timeout_s=timeout_s,
    )


def _config(project: ProjectConfig | None = None) -> LabroConfig:
    return LabroConfig(
        digest=DigestConfig(enabled=False),
        defaults=DefaultsConfig(
            model="claude-code:anthropic/claude-opus-4-7", max_turns=20, timeout_s=600
        ),
        projects=[project or _project()],
    )


# ── unit tests: helper functions ───────────────────────────────────────────────


def test_label_names_extracts_names() -> None:
    item = {"labels": [{"name": "ai-dev"}, {"name": "bug"}]}
    assert _label_names(item) == {"ai-dev", "bug"}


def test_label_names_empty() -> None:
    assert _label_names({}) == set()
    assert _label_names({"labels": []}) == set()


def test_item_type_issue() -> None:
    assert _item_type({"number": 1}) == "issue"


def test_item_type_pr() -> None:
    assert _item_type({"number": 1, "pull_request": {"url": "..."}}) == "pr"


def test_resolve_permitted_actions_rule_wins() -> None:
    rule = _label_rule(permitted_actions=[PermittedAction.OPEN_PR])
    src = _source_config(permitted_actions=[PermittedAction.COMMENT_ON_ISSUE])
    proj = _project(source_cfg=src, permitted_actions=[PermittedAction.COMMENT_ON_PR])
    assert _resolve_permitted_actions(rule, src, proj) == [PermittedAction.OPEN_PR]


def test_resolve_permitted_actions_source_fallback() -> None:
    rule = _label_rule(permitted_actions=None)
    src = _source_config(permitted_actions=[PermittedAction.COMMENT_ON_ISSUE])
    proj = _project(source_cfg=src, permitted_actions=[PermittedAction.COMMENT_ON_PR])
    assert _resolve_permitted_actions(rule, src, proj) == [PermittedAction.COMMENT_ON_ISSUE]


def test_resolve_permitted_actions_project_fallback() -> None:
    rule = _label_rule(permitted_actions=None)
    src = _source_config(permitted_actions=None)
    proj = _project(source_cfg=src, permitted_actions=[PermittedAction.CLOSE_ISSUE])
    assert _resolve_permitted_actions(rule, src, proj) == [PermittedAction.CLOSE_ISSUE]


def test_resolve_permitted_actions_empty_when_none_set() -> None:
    rule = _label_rule(permitted_actions=None)
    src = _source_config(permitted_actions=None)
    proj = _project(source_cfg=src, permitted_actions=None)
    assert _resolve_permitted_actions(rule, src, proj) == []


def test_resolve_model_slug_source_wins() -> None:
    src = _source_config(model="claude-code:anthropic/claude-sonnet-4-6")
    proj = _project(source_cfg=src, model="claude-code:anthropic/claude-haiku-4-5")
    rule = _label_rule()
    assert (
        _resolve_model_slug(rule, src, proj, "claude-code:anthropic/claude-opus-4-7")
        == "claude-code:anthropic/claude-sonnet-4-6"
    )


def test_resolve_model_slug_project_fallback() -> None:
    src = _source_config(model=None)
    proj = _project(source_cfg=src, model="claude-code:anthropic/claude-haiku-4-5")
    rule = _label_rule()
    assert (
        _resolve_model_slug(rule, src, proj, "claude-code:anthropic/claude-opus-4-7")
        == "claude-code:anthropic/claude-haiku-4-5"
    )


def test_resolve_model_slug_defaults_fallback() -> None:
    src = _source_config(model=None)
    proj = _project(source_cfg=src, model=None)
    rule = _label_rule()
    assert (
        _resolve_model_slug(rule, src, proj, "claude-code:anthropic/claude-opus-4-7")
        == "claude-code:anthropic/claude-opus-4-7"
    )


# ── GhLabelTaskSource tests (gh CLI mocked) ───────────────────────────────


@pytest.fixture()
def gh_source_with_rule() -> tuple[GhLabelTaskSource, ProjectConfig, LabroConfig]:
    src_cfg = _source_config(
        rules=[
            _label_rule(
                permitted_actions=[PermittedAction.OPEN_PR, PermittedAction.COMMENT_ON_ISSUE]
            )
        ],
    )
    proj = _project(source_cfg=src_cfg)
    cfg = _config(proj)
    return GhLabelTaskSource(src_cfg), proj, cfg


def test_fetch_task_returns_oldest_eligible(
    gh_source_with_rule: tuple[GhLabelTaskSource, ProjectConfig, LabroConfig],
) -> None:
    """fetch_task picks the oldest item (issue #42, created Jan 15) over #55 (Feb 1)."""
    source, proj, cfg = gh_source_with_rule
    fixture = load_fixture("gh_issues_ai_dev.json")

    with patch("labro.task_sources.gh_label._run_gh_api", side_effect=gh_api_mock(fixture)):
        result = source.fetch_task(
            project=proj,
            defaults_model=cfg.defaults.model,
            defaults_max_turns=cfg.defaults.max_turns,
            defaults_timeout_s=cfg.defaults.timeout_s,
            defaults_max_comments=cfg.defaults.max_comments,
        )

    assert result is not None
    task, _agent_cfg = result
    assert isinstance(task, Task)
    assert task.item_number == 42
    assert task.item_type == "issue"
    assert task.source_label == "ai-dev"
    assert task.done_label == "ai-dev-done"
    assert task.repo == "org/repo"
    assert task.source == "gh-label"
    assert task.grafana_rule_uid is None
    assert task.item_url == "https://github.com/org/repo/issues/42"
    assert "Fix authentication race condition" in task.description


def test_fetch_task_agent_config_defaults(
    gh_source_with_rule: tuple[GhLabelTaskSource, ProjectConfig, LabroConfig],
) -> None:
    """AgentConfig inherits model/max_turns/timeout_s from defaults when not overridden."""
    source, proj, _cfg = gh_source_with_rule
    fixture = load_fixture("gh_issues_ai_dev.json")

    with patch("labro.task_sources.gh_label._run_gh_api", side_effect=gh_api_mock(fixture)):
        result = source.fetch_task(
            project=proj,
            defaults_model="claude-code:anthropic/claude-opus-4-7",
            defaults_max_turns=20,
            defaults_timeout_s=600,
            defaults_max_comments=10,
        )

    assert result is not None
    _, agent_cfg = result
    assert isinstance(agent_cfg, AgentConfig)
    assert agent_cfg.agent == "claude-code"
    assert agent_cfg.slug == "claude-code:anthropic/claude-opus-4-7"
    assert agent_cfg.model == "claude-opus-4-7"
    assert agent_cfg.max_turns == 20
    assert agent_cfg.timeout_s == 600


def test_fetch_task_skips_ai_failed() -> None:
    """Items with ai-failed label are excluded; the clean item (#20) is returned."""
    src_cfg = _source_config(
        rules=[_label_rule(permitted_actions=[PermittedAction.COMMENT_ON_ISSUE])],
    )
    proj = _project(source_cfg=src_cfg)
    cfg = _config(proj)
    source = GhLabelTaskSource(src_cfg)
    fixture = load_fixture("gh_issues_ai_dev_with_failed.json")

    with patch("labro.task_sources.gh_label._run_gh_api", side_effect=gh_api_mock(fixture)):
        result = source.fetch_task(
            project=proj,
            defaults_model=cfg.defaults.model,
            defaults_max_turns=cfg.defaults.max_turns,
            defaults_timeout_s=cfg.defaults.timeout_s,
            defaults_max_comments=cfg.defaults.max_comments,
        )

    assert result is not None
    task, _ = result
    assert task.item_number == 20  # #10 has ai-failed; #20 does not


def test_fetch_task_skips_done_label() -> None:
    """Items carrying the done label are excluded."""
    rule = _label_rule(label="ai-dev", done_label="ai-dev-done")
    src_cfg = _source_config(rules=[rule])
    proj = _project(source_cfg=src_cfg)
    cfg = _config(proj)
    source = GhLabelTaskSource(src_cfg)

    # Inject done_label into first item
    fixture = load_fixture("gh_issues_ai_dev.json")
    fixture[0]["labels"].append({"name": "ai-dev-done", "color": "0e8a16"})

    with patch("labro.task_sources.gh_label._run_gh_api", side_effect=gh_api_mock(fixture)):
        result = source.fetch_task(
            project=proj,
            defaults_model=cfg.defaults.model,
            defaults_max_turns=cfg.defaults.max_turns,
            defaults_timeout_s=cfg.defaults.timeout_s,
            defaults_max_comments=cfg.defaults.max_comments,
        )

    assert result is not None
    task, _ = result
    assert task.item_number == 55  # #42 has done_label; #55 does not


def test_fetch_task_empty_returns_none() -> None:
    """No eligible items → None."""
    src_cfg = _source_config()
    proj = _project(source_cfg=src_cfg)
    cfg = _config(proj)
    source = GhLabelTaskSource(src_cfg)

    with patch("labro.task_sources.gh_label._run_gh_api", return_value=[]):
        result = source.fetch_task(
            project=proj,
            defaults_model=cfg.defaults.model,
            defaults_max_turns=cfg.defaults.max_turns,
            defaults_timeout_s=cfg.defaults.timeout_s,
            defaults_max_comments=cfg.defaults.max_comments,
        )

    assert result is None


def test_fetch_task_detects_pr_item_type() -> None:
    """An item with a pull_request key is classified as item_type='pr'."""
    src_cfg = _source_config(
        rules=[_label_rule(label="ai-review", done_label="ai-review-done")],
    )
    proj = _project(source_cfg=src_cfg)
    cfg = _config(proj)
    source = GhLabelTaskSource(src_cfg)
    fixture = load_fixture("gh_issues_pr.json")

    with patch("labro.task_sources.gh_label._run_gh_api", side_effect=gh_api_mock(fixture)):
        result = source.fetch_task(
            project=proj,
            defaults_model=cfg.defaults.model,
            defaults_max_turns=cfg.defaults.max_turns,
            defaults_timeout_s=cfg.defaults.timeout_s,
            defaults_max_comments=cfg.defaults.max_comments,
        )

    assert result is not None
    task, _ = result
    assert task.item_type == "pr"
    assert task.item_number == 99


def test_fetch_task_multiple_rules_picks_oldest_across_rules() -> None:
    """Candidates from multiple label_rules are pooled; the globally oldest wins."""
    rule_a = _label_rule(
        label="ai-dev", done_label="ai-dev-done", permitted_actions=[PermittedAction.OPEN_PR]
    )
    rule_b = _label_rule(
        label="ai-review",
        done_label="ai-review-done",
        permitted_actions=[PermittedAction.COMMENT_ON_PR],
    )
    src_cfg = _source_config(rules=[rule_a, rule_b])
    proj = _project(source_cfg=src_cfg)
    cfg = _config(proj)
    source = GhLabelTaskSource(src_cfg)

    # rule_a → item #55 created Feb 1; rule_b → item #99 created Mar 1
    fixture_a = load_fixture("gh_issues_ai_dev.json")[1:2]  # only #55
    fixture_b = load_fixture("gh_issues_pr.json")  # #99

    call_count = 0

    def fake_gh_api(args: list[str]) -> Any:
        nonlocal call_count
        result = fixture_a if call_count == 0 else fixture_b
        call_count += 1
        return result

    with patch("labro.task_sources.gh_label._run_gh_api", side_effect=fake_gh_api):
        result = source.fetch_task(
            project=proj,
            defaults_model=cfg.defaults.model,
            defaults_max_turns=cfg.defaults.max_turns,
            defaults_timeout_s=cfg.defaults.timeout_s,
            defaults_max_comments=cfg.defaults.max_comments,
        )

    assert result is not None
    task, _ = result
    assert task.item_number == 55  # Feb 1 is older than Mar 1


def test_fetch_task_project_overrides_applied() -> None:
    """Project-level max_turns and timeout_s override defaults."""
    src_cfg = _source_config(rules=[_label_rule()])
    proj = _project(source_cfg=src_cfg, max_turns=5, timeout_s=120)
    cfg = _config(proj)
    source = GhLabelTaskSource(src_cfg)
    fixture = load_fixture("gh_issues_ai_dev.json")

    with patch("labro.task_sources.gh_label._run_gh_api", side_effect=gh_api_mock(fixture)):
        result = source.fetch_task(
            project=proj,
            defaults_model=cfg.defaults.model,
            defaults_max_turns=cfg.defaults.max_turns,
            defaults_timeout_s=cfg.defaults.timeout_s,
            defaults_max_comments=cfg.defaults.max_comments,
        )

    assert result is not None
    _, agent_cfg = result
    assert agent_cfg.max_turns == 5
    assert agent_cfg.timeout_s == 120


# ── picker tests (stubbed fetch_task) ─────────────────────────────────────────


class _StubSource(GhLabelTaskSource):
    """Configurable stub: returns a fixed result or raises."""

    def __init__(self, result: tuple[Task, AgentConfig] | None | Exception) -> None:
        # Do not call super().__init__() — no real source config needed.
        self._stub_result = result

    def fetch_task(
        self,
        project: ProjectConfig,
        defaults_model: str,
        defaults_max_turns: int,
        defaults_timeout_s: int,
        defaults_max_comments: int,
    ) -> tuple[Task, AgentConfig] | None:
        if isinstance(self._stub_result, Exception):
            raise self._stub_result
        return self._stub_result


def _make_task_and_config() -> tuple[Task, AgentConfig]:
    task = Task(
        task_id="test-id",
        source="gh-label",
        description="Do something",
        permitted_actions=[PermittedAction.COMMENT_ON_ISSUE],
        repo="org/repo",
        item_type="issue",
        item_number=1,
        item_url="https://github.com/org/repo/issues/1",
        source_label="ai-dev",
        done_label="ai-dev-done",
        grafana_rule_uid=None,
    )
    agent_cfg = AgentConfig.from_slug(
        "claude-code:anthropic/claude-opus-4-7", max_turns=20, timeout_s=600
    )
    return task, agent_cfg


def test_picker_returns_task_from_first_source() -> None:
    """pick() returns the result from the first source that yields a task."""
    expected = _make_task_and_config()
    src_cfg = _source_config()
    proj = _project(source_cfg=src_cfg)
    cfg = _config(proj)

    with patch("labro.picker._build_source", return_value=_StubSource(expected)):
        task, agent_cfg = pick(proj, cfg)

    assert task is not None
    assert task.item_number == 1
    assert agent_cfg is not None


def test_picker_returns_none_none_when_all_sources_empty() -> None:
    """pick() returns (None, None) when every source returns None."""
    src_cfg = _source_config()
    proj = _project(source_cfg=src_cfg)
    cfg = _config(proj)

    with patch("labro.picker._build_source", return_value=_StubSource(None)):
        task, agent_cfg = pick(proj, cfg)

    assert task is None
    assert agent_cfg is None


def test_picker_skips_erroring_source_and_tries_next() -> None:
    """A source that raises is skipped; the next source is tried."""
    expected = _make_task_and_config()

    stub_error = _StubSource(RuntimeError("gh not found"))
    stub_ok = _StubSource(expected)

    call_count = 0

    def build_side_effect(
        source_cfg: object, personas: object, perspectives: object
    ) -> _StubSource:
        nonlocal call_count
        stub = stub_error if call_count == 0 else stub_ok
        call_count += 1
        return stub

    rule_a = _label_rule(label="ai-dev", done_label="ai-dev-done")
    rule_b = _label_rule(label="ai-review", done_label="ai-review-done")
    src_a = GhLabelSourceConfig(type="gh-label", label_rules=[rule_a])
    src_b = GhLabelSourceConfig(type="gh-label", label_rules=[rule_b])

    proj = ProjectConfig(
        name="test-project",
        repo="org/repo",
        cron="0 * * * *",
        task_sources=[src_a, src_b],
    )
    cfg = _config(proj)

    with patch("labro.picker._build_source", side_effect=build_side_effect):
        task, agent_cfg = pick(proj, cfg)

    assert task is not None
    assert agent_cfg is not None


def test_picker_returns_none_when_no_sources_configured() -> None:
    """pick() returns (None, None) when the project has no task sources."""
    proj = ProjectConfig(
        name="empty",
        repo="org/repo",
        cron="0 * * * *",
        task_sources=[],
    )
    cfg = _config(proj)
    task, agent_cfg = pick(proj, cfg)
    assert task is None
    assert agent_cfg is None


def test_task_id_is_uuid_format() -> None:
    """Task.task_id is a valid UUID v4 string."""
    import uuid

    src_cfg = _source_config()
    proj = _project(source_cfg=src_cfg)
    cfg = _config(proj)
    source = GhLabelTaskSource(src_cfg)
    fixture = load_fixture("gh_issues_ai_dev.json")

    with patch("labro.task_sources.gh_label._run_gh_api", side_effect=gh_api_mock(fixture)):
        result = source.fetch_task(
            project=proj,
            defaults_model=cfg.defaults.model,
            defaults_max_turns=cfg.defaults.max_turns,
            defaults_timeout_s=cfg.defaults.timeout_s,
            defaults_max_comments=cfg.defaults.max_comments,
        )

    assert result is not None
    task, _ = result
    parsed = uuid.UUID(task.task_id)
    assert parsed.version == 4
