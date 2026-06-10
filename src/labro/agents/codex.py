"""Codex CLI agent implementation.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, ClassVar

from labro.agents._schema import OUTCOME_SCHEMA, validate_structured_output
from labro.agents._subprocess import run_cli
from labro.agents.base import Agent, AgentOutputError
from labro.models import AgentConfig, AgentResult, ItemRef

_log = logging.getLogger(__name__)

_AUTH_JSON_PATH = Path.home() / ".codex" / "auth.json"


class CodexAgent(Agent):
    """Agent implementation that invokes the codex CLI subprocess.

    Codex does not report USD cost; total_cost_usd is always None.
    max_turns is not supported; timeout_s is the only bound.
    """

    id: ClassVar[str] = "codex"
    auth_env_vars: ClassVar[tuple[str, ...]] = ("CODEX_API_KEY",)
    supports_max_turns: ClassVar[bool] = False

    def has_auth(self) -> bool:
        if any(os.environ.get(v) for v in self.auth_env_vars):
            return True
        return _AUTH_JSON_PATH.exists()

    def validate_auth(self) -> tuple[str, str]:
        if os.environ.get("CODEX_API_KEY"):
            return ("WARN", "CODEX_API_KEY: env var present but not validated")
        if _AUTH_JSON_PATH.exists():
            return ("WARN", f"codex auth.json found at {_AUTH_JSON_PATH} (not validated)")
        return ("FAIL", "no Codex auth — set CODEX_API_KEY or run `codex auth login`")

    def invoke(self, prompt: str, config: AgentConfig) -> AgentResult:
        if not self.supports_max_turns:
            _log.info(
                "codex: max_turns setting ignored (not supported); bounded by timeout_s only"
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            schema_path = os.path.join(tmpdir, "schema.json")
            out_path = os.path.join(tmpdir, "out.json")

            with open(schema_path, "w") as f:
                json.dump(OUTCOME_SCHEMA, f)

            cmd: list[str] = ["codex", "exec", "--json"]
            if config.model is not None:
                cmd += ["-m", config.model]
            if config.effort is not None:
                cmd += ["-c", f"model_reasoning_effort={config.effort}"]
            cmd += [
                "--output-schema",
                schema_path,
                "-o",
                out_path,
                "--dangerously-bypass-approvals-and-sandbox",
                "-",
            ]

            stdout, stderr, rc = run_cli(cmd, prompt, config.timeout_s, config.cwd)
            return self._parse_result(stdout, stderr, rc, out_path)

    def _parse_result(
        self,
        stdout: bytes,
        stderr: bytes,
        rc: int,
        out_path: str,
    ) -> AgentResult:
        """Parse JSONL stdout + structured output file into AgentResult."""
        input_tokens = 0
        output_tokens = 0
        cache_read_tokens = 0
        error_event: str | None = None

        for raw_line in stdout.decode(errors="replace").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                event: dict[str, Any] = json.loads(line)
            except json.JSONDecodeError:
                continue

            event_type = event.get("type", "")
            if event_type == "turn.completed":
                usage = event.get("usage") or {}
                input_tokens = int(usage.get("input_tokens", 0))
                output_tokens = int(usage.get("output_tokens", 0))
                cache_read_tokens = int(usage.get("cached_input_tokens", 0))
            elif event_type in ("error", "turn.failed"):
                error_event = event.get("message") or event_type

        # Attempt to read structured output file
        so: Any = None
        try:
            with open(out_path) as f:
                so = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            _log.warning("codex: could not read output file %s: %s", out_path, exc)

        if rc != 0 or so is None or error_event is not None:
            if stdout:
                _log.warning("codex stdout: %s", stdout.decode(errors="replace")[:2000])
            if stderr:
                _log.warning("codex stderr: %s", stderr.decode(errors="replace")[:2000])
            reason = error_event or f"exit_code_{rc}"
            raise AgentOutputError(reason)

        try:
            validate_structured_output(so)
        except AgentOutputError as exc:
            raise AgentOutputError(f"codex structured output invalid: {exc}") from exc

        items_created: list[ItemRef] = [
            ItemRef(item_type=item["item_type"], item_number=item["number"])
            for item in so.get("items_created", [])
        ]

        return AgentResult(
            outcome=so["outcome"],
            summary=so["summary"],
            actions_taken=list(so.get("actions_taken", [])),
            items_created=items_created,
            failure_reason=so.get("failure_reason"),
            total_cost_usd=None,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
        )
