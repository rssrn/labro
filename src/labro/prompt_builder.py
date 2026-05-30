"""Four-section prompt constructor.

Pure function — no I/O.  Sections are separated by ``---`` dividers and
delivered in the order mandated by ARCHITECTURE Design Notes lines 989-997:

  1. Role + harness context
  2. Task
  3. Permitted actions (effective set; all other actions explicitly forbidden)
  4. Project context (repo, default branch, CLAUDE.md instruction, optional extra context)

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

from labro.config.schema import PermittedAction
from labro.models import Task

# Human-readable labels for each PermittedAction value.
# Used to produce the "You may / You must not" enumeration in section 3.
_ACTION_LABELS: dict[PermittedAction, str] = {
    PermittedAction.COMMENT_ON_ISSUE: "post a comment on the in-scope GitHub issue",
    PermittedAction.COMMENT_ON_PR: "post a comment on a GitHub pull request",
    PermittedAction.OPEN_PR: "open a pull request",
    PermittedAction.MERGE_PR: "merge a pull request",
    PermittedAction.PUSH_DEFAULT: "push directly to the default branch",
    PermittedAction.CLOSE_ISSUE: "close the in-scope GitHub issue",
    PermittedAction.CREATE_ISSUE: "create a new GitHub issue",
}

# Comment actions are low-risk: they appear in "You may" when permitted, but are
# NOT enumerated in "You must not" when absent — the agent may still comment on
# related items (e.g. a PR linked to the in-scope issue) at its discretion.
_COMMENT_ACTIONS: frozenset[PermittedAction] = frozenset(
    {PermittedAction.COMMENT_ON_ISSUE, PermittedAction.COMMENT_ON_PR}
)

_DIVIDER = "\n---\n"


def _section_role(persona_prompt: str | None = None, durable_progress: bool = False) -> str:
    base = (
        "You are an autonomous coding agent running unattended on a schedule."
        " No human is present during this session.\n\n"
        "Act decisively within your permitted actions (listed below under **Action permissions**)."
        " If you cannot make meaningful progress within those boundaries, write a"
        " brief explanation and stop — do **not** ask clarifying questions, request"
        " approval, or wait for input."
    )
    if durable_progress:
        base += (
            "\n\nIf this task may take a while, post an early comment on the in-scope item"
            " summarising your plan, and update that same comment as you make progress"
            " (e.g. `gh issue comment <n> --edit-last`). This ensures your analysis"
            " survives if the session ends before you finish."
        )
    if persona_prompt:
        return base + "\n\n" + persona_prompt.strip()
    return base


def _section_task(task: Task) -> str:
    lines: list[str] = ["## Task"]
    if task.item_url:
        lines.append(f"**URL:** {task.item_url}")
    lines.append("")
    lines.append(task.description)
    return "\n".join(lines)


def _section_permitted_actions(task: Task) -> str:
    permitted_set: set[PermittedAction] = set(task.permitted_actions)
    all_actions: list[PermittedAction] = list(PermittedAction)

    allowed = [a for a in all_actions if a in permitted_set]
    # Comment actions are omitted from the forbidden list — they are low-risk
    # and the agent may legitimately use them even when not explicitly granted.
    forbidden = [a for a in all_actions if a not in permitted_set and a not in _COMMENT_ACTIONS]

    lines: list[str] = ["## Action permissions"]
    lines.append(
        "Read operations, web searches, MCP tool calls, and local file operations"
        " are always unrestricted.\n"
    )

    if allowed:
        you_may = "; ".join(_ACTION_LABELS[a] for a in allowed)
        lines.append(f"**You may:** {you_may}.")
    else:
        lines.append("**You may not** perform any GitHub write operations in this run.")

    if forbidden:
        you_must_not = "; ".join(_ACTION_LABELS[a] for a in forbidden)
        lines.append(f"**You must not:** {you_must_not}.")

    return "\n".join(lines)


def _section_project_context(
    task: Task,
    default_branch: str,
    extra_context: str | None,
    wip_branch: str | None = None,
    prior_summary: str | None = None,
) -> str:
    lines: list[str] = ["## Project context"]
    lines.append(f"**Repository:** {task.repo}")
    lines.append(f"**Default branch:** {default_branch}")
    lines.append("")
    lines.append(
        "Read `CLAUDE.md` at the repository root before taking any action."
        " It encodes project-specific conventions, no-go zones, and style rules"
        " that take precedence over your general defaults."
    )
    if wip_branch is not None:
        lines.append("")
        lines.append(
            f"**Resuming from a previous partial run.** The working copy has been"
            f" checked out to branch `{wip_branch}`, which contains code changes"
            f" from the previous session. Review what was already changed before"
            f" continuing — do not duplicate work that is already done."
        )
        if prior_summary:
            lines.append("")
            lines.append("**Previous session summary:**")
            lines.append(prior_summary.strip())
    if extra_context:
        lines.append("")
        lines.append(extra_context.strip())
    return "\n".join(lines)


def build_prompt(
    task: Task,
    project_context: str | None = None,
    default_branch: str = "main",
    wip_branch: str | None = None,
    prior_summary: str | None = None,
) -> str:
    """Construct the four-section agent prompt for *task*.

    Args:
        task: Resolved task produced by the picker.
        project_context: Optional free-text from ``labro.toml`` ``context`` field;
            appended verbatim to section 4.
        default_branch: Default branch of the managed repo (defaults to ``"main"``).
        wip_branch: WIP branch checked out for a resume run (e.g. ``labro-wip/<id>``);
            included in section 4 to inform the agent it is resuming.
        prior_summary: Summary text from the previous partial run; appended under
            the resume notice in section 4.

    Returns:
        The full prompt string ready to be piped to ``claude -p`` via stdin.
    """
    has_item = task.item_number is not None
    has_comment = any(
        a in (PermittedAction.COMMENT_ON_ISSUE, PermittedAction.COMMENT_ON_PR)
        for a in task.permitted_actions
    )
    sections = [
        _section_role(task.persona_prompt, durable_progress=has_item and has_comment),
        _section_task(task),
        _section_permitted_actions(task),
        _section_project_context(task, default_branch, project_context, wip_branch, prior_summary),
    ]
    return _DIVIDER.join(sections)
