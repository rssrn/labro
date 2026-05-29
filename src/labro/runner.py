"""Claude Code CLI subprocess runner.

Invokes the ``claude`` CLI as a subprocess, parses the structured JSON
response, validates the ``structured_output`` payload, and returns an
:class:`~labro.models.AgentResult`.

Prompt is passed via **stdin** (not as a CLI arg) to avoid ARG_MAX limits.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import json
import logging
import subprocess
from typing import Any

from labro.config.schema import PermittedAction
from labro.models import AgentConfig, AgentResult, ItemRef

_log = logging.getLogger(__name__)

# Read-only tools always granted — safe baseline for any task.
# Edit/Write included because the agent runs in a cloned repo; file changes are
# harmless without an explicit PUSH_DEFAULT permitted action.
_BASE_TOOLS: list[str] = [
    "Read",
    "Edit",
    "Write",
    "WebFetch",
    "Bash(gh issue view *)",
    "Bash(gh issue list *)",
    "Bash(gh pr view *)",
    "Bash(gh pr list *)",
    "Bash(gh api *)",
    "Bash(git log *)",
    "Bash(git diff *)",
    "Bash(git status)",
    "Bash(git show *)",
]

# Maps each PermittedAction to the gh/git command patterns it requires.
_ACTION_TOOLS: dict[PermittedAction, list[str]] = {
    PermittedAction.COMMENT_ON_ISSUE: ["Bash(gh issue comment *)"],
    PermittedAction.COMMENT_ON_PR: ["Bash(gh pr comment *)", "Bash(gh pr review *)"],
    PermittedAction.OPEN_PR: ["Bash(gh pr create *)", "Bash(gh pr edit *)"],
    PermittedAction.MERGE_PR: ["Bash(gh pr merge *)"],
    PermittedAction.PUSH_DEFAULT: ["Bash(git push *)"],
    PermittedAction.CLOSE_ISSUE: ["Bash(gh issue close *)"],
    PermittedAction.CREATE_ISSUE: ["Bash(gh issue create *)"],
}


def _build_allowed_tools(permitted_actions: list[PermittedAction]) -> list[str]:
    """Return the --allowedTools list for the given permitted actions."""
    tools = list(_BASE_TOOLS)
    for action in permitted_actions:
        tools.extend(_ACTION_TOOLS.get(action, []))
    return tools


# JSON schema passed to ``--json-schema`` so the model populates
# ``structured_output`` in the response.  Must match ARCHITECTURE §11 Design
# Notes (lines 1162-1189).
JSON_SCHEMA_STR: str = json.dumps(
    {
        "type": "object",
        "properties": {
            "outcome": {
                "type": "string",
                "enum": ["success", "failure", "partial"],
            },
            "summary": {"type": "string"},
            "actions_taken": {
                "type": "array",
                "items": {"type": "string"},
            },
            "items_created": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "item_type": {
                            "type": "string",
                            "enum": ["issue", "pr"],
                        },
                        "number": {"type": "integer"},
                    },
                    "required": ["item_type", "number"],
                },
            },
            "failure_reason": {"type": "string"},
        },
        "required": ["outcome", "summary", "actions_taken", "items_created"],
    }
)

_VALID_OUTCOMES = {"success", "failure", "partial"}


class RunnerTimeoutError(Exception):
    """Raised when the ``claude`` subprocess exceeds its configured timeout."""


class RunnerOutputError(Exception):
    """Raised when the ``claude`` response cannot be validated."""


def _validate_structured_output(so: Any) -> None:
    """Validate *so* against the expected ``structured_output`` shape.

    Raises :class:`RunnerOutputError` with a descriptive message on any
    violation.
    """
    if not isinstance(so, dict):
        raise RunnerOutputError(
            f"structured_output must be a JSON object, got {type(so).__name__}"
        )

    # outcome
    outcome = so.get("outcome")
    if outcome not in _VALID_OUTCOMES:
        raise RunnerOutputError(
            f"structured_output.outcome must be one of {sorted(_VALID_OUTCOMES)}, got {outcome!r}"
        )

    # summary
    summary = so.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise RunnerOutputError("structured_output.summary must be a non-empty string")

    # actions_taken
    at = so.get("actions_taken")
    if not isinstance(at, list) or not all(isinstance(x, str) for x in at):
        raise RunnerOutputError("structured_output.actions_taken must be a list of strings")

    # items_created
    ic = so.get("items_created")
    if not isinstance(ic, list):
        raise RunnerOutputError("structured_output.items_created must be an array")
    for idx, item in enumerate(ic):
        if not isinstance(item, dict):
            raise RunnerOutputError(f"structured_output.items_created[{idx}] must be an object")
        if item.get("item_type") not in {"issue", "pr"}:
            raise RunnerOutputError(
                f"structured_output.items_created[{idx}].item_type must be "
                f"'issue' or 'pr', got {item.get('item_type')!r}"
            )
        if not isinstance(item.get("number"), int):
            raise RunnerOutputError(
                f"structured_output.items_created[{idx}].number must be an integer"
            )


def run_claude(prompt: str, config: AgentConfig) -> AgentResult:
    """Invoke ``claude -p`` with *prompt* (via stdin) and return :class:`AgentResult`.

    Args:
        prompt: Four-section prompt string from ``prompt_builder``.
        config: Resolved agent invocation parameters.

    Returns:
        Parsed and validated :class:`AgentResult`.

    Raises:
        RunnerTimeoutError: If the subprocess exceeds ``config.timeout_s``.
        RunnerOutputError: If the response JSON is missing or has invalid
            ``structured_output``.
    """
    allowed_tools = _build_allowed_tools(config.permitted_actions)
    cmd = [
        "claude",
        "-p",
        "--model",
        config.model,
        "--max-turns",
        str(config.max_turns),
        "--output-format",
        "json",
        "--json-schema",
        JSON_SCHEMA_STR,
        "--allowedTools",
        *allowed_tools,
    ]
    if config.effort is not None:
        cmd += ["--effort", config.effort]

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=config.cwd,  # None → inherits caller cwd; set to repo_path in live runs
        shell=False,
    )

    try:
        stdout, stderr = proc.communicate(input=prompt.encode(), timeout=config.timeout_s)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()  # drain to avoid blocking
        raise RunnerTimeoutError(
            f"claude subprocess exceeded timeout of {config.timeout_s}s"
        ) from None

    # Parse top-level JSON
    try:
        response: dict[str, Any] = json.loads(stdout.decode())
    except json.JSONDecodeError as exc:
        if stderr:
            _log.warning("claude stderr: %s", stderr.decode(errors="replace"))
        raise RunnerOutputError(f"Failed to parse claude JSON response: {exc}") from exc

    # Extract top-level fields
    is_error: bool = bool(response.get("is_error", False))
    subtype: str = str(response.get("subtype", ""))
    num_turns: int = int(response.get("num_turns", 0))
    total_cost_usd: float = float(response.get("total_cost_usd", 0.0))
    duration_ms: int = int(response.get("duration_ms", 0))

    usage: dict[str, Any] = response.get("usage") or {}
    input_tokens: int = int(usage.get("input_tokens", 0))
    output_tokens: int = int(usage.get("output_tokens", 0))
    cache_read_tokens: int = int(usage.get("cache_read_input_tokens", 0))
    cache_write_tokens: int = int(usage.get("cache_creation_input_tokens", 0))

    # Validate structured_output
    so = response.get("structured_output")
    if so is None:
        if subtype:
            _log.warning("claude error subtype: %s", subtype)
        _log.warning(
            "claude response missing structured_output; top-level keys=%s is_error=%s subtype=%r",
            sorted(response.keys()),
            is_error,
            subtype,
        )
        if stderr:
            _log.warning("claude stderr: %s", stderr.decode(errors="replace"))
        raise RunnerOutputError("claude response missing required 'structured_output' key")
    _validate_structured_output(so)

    # Build AgentResult from validated structured_output
    outcome: str = so["outcome"]

    # Failure detection: is_error==True OR subtype != "success" → override outcome
    if is_error or subtype != "success":
        outcome = "failure"

    items_created: list[ItemRef] = [
        ItemRef(item_type=item["item_type"], item_number=item["number"])
        for item in so.get("items_created", [])
    ]

    return AgentResult(
        outcome=outcome,
        summary=so["summary"],
        actions_taken=list(so.get("actions_taken", [])),
        items_created=items_created,
        failure_reason=so.get("failure_reason"),
        is_error=is_error,
        num_turns=num_turns,
        total_cost_usd=total_cost_usd,
        duration_ms=duration_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
    )
