"""Shared structured-output JSON schema and validator for all agent implementations.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import json
from typing import Any

from labro.agents.base import AgentOutputError

OUTCOME_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
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
                "additionalProperties": False,
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
        "failure_reason": {"type": ["string", "null"]},
    },
    "required": ["outcome", "summary", "actions_taken", "items_created", "failure_reason"],
}

OUTCOME_SCHEMA_STR: str = json.dumps(OUTCOME_SCHEMA)

_VALID_OUTCOMES = {"success", "failure", "partial"}


def validate_structured_output(so: Any) -> None:
    """Validate *so* against the expected structured_output shape.

    Raises AgentOutputError with a descriptive message on any violation.
    """
    if not isinstance(so, dict):
        raise AgentOutputError(f"structured_output must be a JSON object, got {type(so).__name__}")

    outcome = so.get("outcome")
    if outcome not in _VALID_OUTCOMES:
        raise AgentOutputError(
            f"structured_output.outcome must be one of {sorted(_VALID_OUTCOMES)}, got {outcome!r}"
        )

    summary = so.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        raise AgentOutputError("structured_output.summary must be a non-empty string")

    at = so.get("actions_taken")
    if not isinstance(at, list) or not all(isinstance(x, str) for x in at):
        raise AgentOutputError("structured_output.actions_taken must be a list of strings")

    ic = so.get("items_created")
    if not isinstance(ic, list):
        raise AgentOutputError("structured_output.items_created must be an array")
    for idx, item in enumerate(ic):
        if not isinstance(item, dict):
            raise AgentOutputError(f"structured_output.items_created[{idx}] must be an object")
        if item.get("item_type") not in {"issue", "pr"}:
            raise AgentOutputError(
                f"structured_output.items_created[{idx}].item_type must be "
                f"'issue' or 'pr', got {item.get('item_type')!r}"
            )
        if not isinstance(item.get("number"), int):
            raise AgentOutputError(
                f"structured_output.items_created[{idx}].number must be an integer"
            )
