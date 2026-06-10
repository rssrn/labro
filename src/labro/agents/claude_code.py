"""Claude Code agent implementation.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any, ClassVar

from labro.agents._schema import OUTCOME_SCHEMA_STR, validate_structured_output
from labro.agents._subprocess import run_cli
from labro.agents.base import Agent, AgentOutputError
from labro.config.schema import PermittedAction
from labro.models import AgentConfig, AgentResult, ItemRef

_log = logging.getLogger(__name__)

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

_ACTION_TOOLS: dict[PermittedAction, list[str]] = {
    PermittedAction.COMMENT_ON_ISSUE: ["Bash(gh issue comment *)"],
    PermittedAction.COMMENT_ON_PR: ["Bash(gh pr comment *)", "Bash(gh pr review *)"],
    PermittedAction.OPEN_PR: ["Bash(gh pr create *)", "Bash(gh pr edit *)"],
    PermittedAction.MERGE_PR: ["Bash(gh pr merge *)"],
    PermittedAction.PUSH_DEFAULT: ["Bash(git push *)"],
    PermittedAction.CLOSE_ISSUE: ["Bash(gh issue close *)"],
    PermittedAction.CREATE_ISSUE: ["Bash(gh issue create *)"],
}

_SESSION_LIMIT_MARKER = "session limit"


def _build_allowed_tools(permitted_actions: list[PermittedAction]) -> list[str]:
    """Return the --allowedTools list for the given permitted actions."""
    tools = list(_BASE_TOOLS)
    for action in permitted_actions:
        tools.extend(_ACTION_TOOLS.get(action, []))
    return tools


def _check_anthropic_api_key(api_key: str) -> tuple[str, str]:
    """Validate ANTHROPIC_API_KEY via GET /v1/models (no tokens spent)."""
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/models",
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10):
            return ("OK  ", "ANTHROPIC_API_KEY: valid (GET /v1/models succeeded)")
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            return ("FAIL", "ANTHROPIC_API_KEY: invalid or expired (401 Unauthorized)")
        return ("WARN", f"ANTHROPIC_API_KEY: unexpected HTTP {exc.code} from /v1/models")
    except Exception as exc:
        return ("WARN", f"ANTHROPIC_API_KEY: could not reach api.anthropic.com: {exc}")


def run_claude(prompt: str, config: AgentConfig) -> AgentResult:
    """Invoke claude -p with prompt (via stdin) and return AgentResult.

    Raises AgentTimeoutError or AgentOutputError on failure.
    """
    allowed_tools = _build_allowed_tools(config.permitted_actions)
    cmd: list[str] = ["claude", "-p"]
    if config.model is not None:
        cmd += ["--model", config.model]
    cmd += [
        "--max-turns",
        str(config.max_turns),
        "--output-format",
        "json",
        "--json-schema",
        OUTCOME_SCHEMA_STR,
        "--allowedTools",
        *allowed_tools,
    ]
    if config.effort is not None:
        cmd += ["--effort", config.effort]

    stdout, stderr, _rc = run_cli(cmd, prompt, config.timeout_s, config.cwd)

    try:
        response: dict[str, Any] = json.loads(stdout.decode())
    except json.JSONDecodeError as exc:
        if stderr:
            _log.warning("claude stderr: %s", stderr.decode(errors="replace"))
        raise AgentOutputError(f"Failed to parse claude JSON response: {exc}") from exc

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
        result_text: str = str(response.get("result") or "")
        if _SESSION_LIMIT_MARKER in result_text.lower():
            _log.warning("session limit hit: %s", result_text)
            so_outcome = "failure"
            so_summary = result_text or "Session limit reached."
            so_failure_reason: str | None = "session_limit_hit"
        elif subtype == "error_max_turns":
            so_outcome = "partial"
            so_summary = result_text or "Agent reached the turn limit before completing the task."
            so_failure_reason = subtype
        else:
            raise AgentOutputError(subtype or "claude terminated without a structured result")
        return AgentResult(
            outcome=so_outcome,
            summary=so_summary,
            failure_reason=so_failure_reason,
            is_error=is_error,
            num_turns=num_turns,
            total_cost_usd=total_cost_usd,
            duration_ms=duration_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
        )
    validate_structured_output(so)

    outcome: str = so["outcome"]
    if is_error or subtype != "success":
        if outcome == "success":
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


class ClaudeCodeAgent(Agent):
    """Agent implementation that invokes the claude CLI subprocess."""

    id: ClassVar[str] = "claude-code"
    auth_env_vars: ClassVar[tuple[str, ...]] = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")
    supports_max_turns: ClassVar[bool] = True

    def invoke(self, prompt: str, config: AgentConfig) -> AgentResult:
        return run_claude(prompt, config)

    def validate_auth(self) -> tuple[str, str]:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if api_key:
            return _check_anthropic_api_key(api_key)
        if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
            return ("WARN", "CLAUDE_CODE_OAUTH_TOKEN: env var present but not validated")
        return ("FAIL", "no Claude auth — set ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN")
