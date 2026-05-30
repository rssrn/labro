"""Tests for prompt_builder.py.

Asserts:
- Exactly four sections are present in the output, in correct order.
- Permitted-actions section enumerates only the effective set.
- No section is empty.
- Item URL and item type/number appear in section 2.
- Project context (repo, branch, CLAUDE.md instruction) appears in section 4.
- Optional extra context is appended to section 4.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import pytest

from labro.config.schema import PermittedAction
from labro.models import Task
from labro.prompt_builder import _DIVIDER, build_prompt

# ── shared helpers ─────────────────────────────────────────────────────────────

_ALL_ACTIONS: list[PermittedAction] = list(PermittedAction)


def _task(
    permitted_actions: list[PermittedAction] | None = None,
    description: str = "Fix the broken authentication flow.\n\nSee details in the issue.",
    item_type: str | None = "issue",
    item_number: int | None = 42,
    item_url: str | None = "https://github.com/org/repo/issues/42",
    repo: str = "org/repo",
) -> Task:
    return Task(
        task_id="test-task-id",
        source="gh-label",
        description=description,
        permitted_actions=permitted_actions
        if permitted_actions is not None
        else [PermittedAction.COMMENT_ON_ISSUE],
        repo=repo,
        item_type=item_type,
        item_number=item_number,
        item_url=item_url,
        source_label="ai-dev",
        done_label="ai-dev-done",
        grafana_rule_uid=None,
    )


# ── section-structure tests ────────────────────────────────────────────────────


def test_prompt_has_exactly_four_sections() -> None:
    """build_prompt returns a string with exactly four ---  separated sections."""
    prompt = build_prompt(_task())
    sections = prompt.split(_DIVIDER)
    assert len(sections) == 4, f"Expected 4 sections, got {len(sections)}"


def test_no_section_is_empty() -> None:
    """Every section contains non-whitespace content."""
    prompt = build_prompt(_task())
    for i, section in enumerate(prompt.split(_DIVIDER), start=1):
        assert section.strip(), f"Section {i} is empty"


def test_sections_in_correct_order() -> None:
    """Sections appear in the canonical order: role, task, permissions, context."""
    prompt = build_prompt(_task())
    sections = prompt.split(_DIVIDER)

    # Section 1: role context — autonomous agent, unattended
    assert "unattended" in sections[0].lower()
    assert "autonomous" in sections[0].lower()

    # Section 2: task — must contain the task description
    assert "Task" in sections[1]
    assert "Fix the broken authentication flow" in sections[1]

    # Section 3: permitted actions
    assert "Action permissions" in sections[2] or "permission" in sections[2].lower()

    # Section 4: project context — must mention the repo and CLAUDE.md
    assert "org/repo" in sections[3]
    assert "CLAUDE.md" in sections[3]


# ── section 2 — task content ───────────────────────────────────────────────────


def test_section_2_contains_item_url() -> None:
    prompt = build_prompt(_task())
    task_section = prompt.split(_DIVIDER)[1]
    assert "https://github.com/org/repo/issues/42" in task_section


def test_section_2_contains_full_description() -> None:
    prompt = build_prompt(_task(description="My full description text here."))
    task_section = prompt.split(_DIVIDER)[1]
    assert "My full description text here." in task_section


# ── section 3 — permitted actions ─────────────────────────────────────────────


def test_section_3_enumerates_only_permitted_actions() -> None:
    """Permitted-actions section lists only the effective actions as 'You may'."""
    allowed = [PermittedAction.COMMENT_ON_ISSUE, PermittedAction.OPEN_PR]
    prompt = build_prompt(_task(permitted_actions=allowed))
    perm_section = prompt.split(_DIVIDER)[2]

    assert "post a comment on the in-scope GitHub issue" in perm_section
    assert "open a pull request" in perm_section


def test_section_3_lists_forbidden_actions() -> None:
    """Impactful actions not in the effective set appear under 'You must not'."""
    allowed = [PermittedAction.COMMENT_ON_ISSUE]
    prompt = build_prompt(_task(permitted_actions=allowed))
    perm_section = prompt.split(_DIVIDER)[2]

    assert "must not" in perm_section.lower()
    # OPEN_PR is not permitted → must appear in forbidden list
    assert "open a pull request" in perm_section


def test_section_3_comment_on_pr_omitted_from_forbidden() -> None:
    """COMMENT_ON_PR is never listed under 'must not', even when not permitted."""
    prompt = build_prompt(_task(permitted_actions=[PermittedAction.COMMENT_ON_ISSUE]))
    perm_section = prompt.split(_DIVIDER)[2]
    # The "must not" clause must not mention PR commenting
    must_not_part = (
        perm_section.lower().split("must not")[-1] if "must not" in perm_section.lower() else ""
    )
    assert "post a comment on a github pull request" not in must_not_part


def test_section_3_comment_on_pr_appears_in_may_when_permitted() -> None:
    """COMMENT_ON_PR appears in 'You may' when it is in the permitted set."""
    allowed = [PermittedAction.COMMENT_ON_ISSUE, PermittedAction.COMMENT_ON_PR]
    prompt = build_prompt(_task(permitted_actions=allowed))
    perm_section = prompt.split(_DIVIDER)[2]
    assert "post a comment on a github pull request" in perm_section.lower()


def test_section_3_empty_permitted_actions() -> None:
    """When no actions are permitted, section 3 clearly states this."""
    prompt = build_prompt(_task(permitted_actions=[]))
    perm_section = prompt.split(_DIVIDER)[2]
    assert "may not" in perm_section.lower() or "must not" in perm_section.lower()


def test_section_3_all_actions_permitted() -> None:
    """When all actions are permitted, 'You must not' is absent or empty."""
    prompt = build_prompt(_task(permitted_actions=_ALL_ACTIONS))
    perm_section = prompt.split(_DIVIDER)[2]
    # All actions in the "You may" line; "must not" clause should not appear
    assert "must not" not in perm_section.lower()


def test_section_3_unrestricted_read_operations_noted() -> None:
    """Section 3 must note that read operations are always unrestricted."""
    prompt = build_prompt(_task())
    perm_section = prompt.split(_DIVIDER)[2]
    assert "unrestricted" in perm_section.lower()


# ── section 4 — project context ───────────────────────────────────────────────


def test_section_4_contains_repo() -> None:
    prompt = build_prompt(_task(repo="acme/widget"))
    ctx_section = prompt.split(_DIVIDER)[3]
    assert "acme/widget" in ctx_section


def test_section_4_contains_default_branch() -> None:
    prompt = build_prompt(_task(), default_branch="develop")
    ctx_section = prompt.split(_DIVIDER)[3]
    assert "develop" in ctx_section


def test_section_4_instructs_claude_md_read() -> None:
    prompt = build_prompt(_task())
    ctx_section = prompt.split(_DIVIDER)[3]
    assert "CLAUDE.md" in ctx_section


def test_section_4_appends_extra_context_when_present() -> None:
    extra = "This project uses strict semantic versioning. Never bump the major version."
    prompt = build_prompt(_task(), project_context=extra)
    ctx_section = prompt.split(_DIVIDER)[3]
    assert extra in ctx_section


def test_section_4_no_extra_context_when_none() -> None:
    """Passing project_context=None does not insert a 'None' literal."""
    prompt = build_prompt(_task(), project_context=None)
    ctx_section = prompt.split(_DIVIDER)[3]
    assert "None" not in ctx_section


# ── round-trip / integration ───────────────────────────────────────────────────


def test_prompt_is_string() -> None:
    assert isinstance(build_prompt(_task()), str)


def test_prompt_deterministic() -> None:
    """Same inputs produce identical output."""
    t = _task()
    assert build_prompt(t) == build_prompt(t)


# ── persona prompt ─────────────────────────────────────────────────────────────


def test_persona_prompt_appears_in_section_1() -> None:
    """When task.persona_prompt is set it is included in the role section."""
    snippet = "Act as a senior developer and raise a PR if reasonably possible."
    task = _task()
    task.persona_prompt = snippet
    role_section = build_prompt(task).split(_DIVIDER)[0]
    assert snippet in role_section


def test_persona_prompt_does_not_add_fifth_section() -> None:
    """A persona prompt must not create a fifth section."""
    task = _task()
    task.persona_prompt = "Act as a business analyst."
    assert len(build_prompt(task).split(_DIVIDER)) == 4


def test_no_persona_prompt_section_1_unchanged() -> None:
    """Without a persona_prompt, section 1 is identical to the baseline."""
    baseline = build_prompt(_task()).split(_DIVIDER)[0]
    task_no_persona = _task()
    task_no_persona.persona_prompt = None
    assert build_prompt(task_no_persona).split(_DIVIDER)[0] == baseline


@pytest.mark.parametrize(
    "action",
    [
        PermittedAction.COMMENT_ON_ISSUE,
        PermittedAction.COMMENT_ON_PR,
        PermittedAction.OPEN_PR,
        PermittedAction.MERGE_PR,
        PermittedAction.PUSH_DEFAULT,
        PermittedAction.CLOSE_ISSUE,
        PermittedAction.CREATE_ISSUE,
    ],
)
def test_each_action_appears_in_may_when_permitted(action: PermittedAction) -> None:
    """Every PermittedAction appears in 'You may' when it is in the permitted set."""
    from labro.prompt_builder import _ACTION_LABELS

    prompt = build_prompt(_task(permitted_actions=[action]))
    perm_section = prompt.split(_DIVIDER)[2]
    assert _ACTION_LABELS[action] in perm_section


@pytest.mark.parametrize(
    "action",
    [
        PermittedAction.OPEN_PR,
        PermittedAction.MERGE_PR,
        PermittedAction.PUSH_DEFAULT,
        PermittedAction.CLOSE_ISSUE,
        PermittedAction.CREATE_ISSUE,
    ],
)
def test_impactful_action_appears_in_must_not_when_absent(action: PermittedAction) -> None:
    """Impactful actions (non-comment) appear in 'must not' when not permitted."""
    from labro.prompt_builder import _ACTION_LABELS

    others: list[PermittedAction] = [a for a in _ALL_ACTIONS if a != action]
    prompt = build_prompt(_task(permitted_actions=others))
    perm_section = prompt.split(_DIVIDER)[2]
    assert _ACTION_LABELS[action] in perm_section


# ── durable-progress guidance ──────────────────────────────────────────────────


def test_durable_progress_present_with_item_and_comment_permission() -> None:
    """Durable-progress guidance appears when item_number set and COMMENT_ON_ISSUE permitted."""
    task = _task(
        item_number=42,
        permitted_actions=[PermittedAction.COMMENT_ON_ISSUE],
    )
    prompt = build_prompt(task)
    role_section = prompt.split(_DIVIDER)[0]
    assert "gh issue comment" in role_section
    assert "--edit-last" in role_section


def test_durable_progress_present_with_comment_on_pr() -> None:
    """Durable-progress guidance appears when COMMENT_ON_PR is the permitted comment action."""
    task = _task(
        item_number=7,
        permitted_actions=[PermittedAction.COMMENT_ON_PR],
    )
    prompt = build_prompt(task)
    role_section = prompt.split(_DIVIDER)[0]
    assert "--edit-last" in role_section


def test_durable_progress_absent_without_item_number() -> None:
    """No durable-progress guidance when item_number is None (no specific item)."""
    task = _task(
        item_number=None,
        permitted_actions=[PermittedAction.COMMENT_ON_ISSUE],
    )
    prompt = build_prompt(task)
    role_section = prompt.split(_DIVIDER)[0]
    assert "--edit-last" not in role_section


def test_durable_progress_absent_without_comment_permission() -> None:
    """No durable-progress guidance when no comment action is permitted."""
    task = _task(
        item_number=42,
        permitted_actions=[PermittedAction.OPEN_PR, PermittedAction.PUSH_DEFAULT],
    )
    prompt = build_prompt(task)
    role_section = prompt.split(_DIVIDER)[0]
    assert "--edit-last" not in role_section


# ── wip_branch resume context ──────────────────────────────────────────────────


def test_wip_branch_appears_in_section_4() -> None:
    """When wip_branch is set, section 4 names the branch and says 'Resuming'."""
    prompt = build_prompt(_task(), wip_branch="labro-wip/prior-run-id")
    ctx_section = prompt.split(_DIVIDER)[3]
    assert "labro-wip/prior-run-id" in ctx_section
    assert "Resuming" in ctx_section


def test_wip_branch_prior_summary_appears_in_section_4() -> None:
    """When prior_summary is set alongside wip_branch, it appears in section 4."""
    prompt = build_prompt(
        _task(),
        wip_branch="labro-wip/prior-run-id",
        prior_summary="Fixed the auth token parsing; PR draft opened.",
    )
    ctx_section = prompt.split(_DIVIDER)[3]
    assert "Fixed the auth token parsing" in ctx_section


def test_wip_branch_none_no_resume_text() -> None:
    """When wip_branch is None, no 'Resuming' text appears in section 4."""
    prompt = build_prompt(_task(), wip_branch=None)
    ctx_section = prompt.split(_DIVIDER)[3]
    assert "Resuming" not in ctx_section


def test_wip_branch_does_not_create_fifth_section() -> None:
    """Adding wip_branch must not create a fifth prompt section."""
    prompt = build_prompt(_task(), wip_branch="labro-wip/run-abc")
    assert len(prompt.split(_DIVIDER)) == 4
