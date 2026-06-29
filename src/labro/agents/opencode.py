"""OpenCode CLI agent implementation.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import subprocess
from collections.abc import Generator
from pathlib import Path
from typing import Any, ClassVar

from labro.agents._schema import OUTCOME_SCHEMA_STR, validate_structured_output
from labro.agents.base import Agent, AgentOutputError, AgentTimeoutError
from labro.models import AgentConfig, AgentResult, ItemRef

_log = logging.getLogger(__name__)

# Well-known provider env vars checked at validate_auth time.
_KNOWN_PROVIDER_KEYS: tuple[str, ...] = (
    "ANTHROPIC_API_KEY",
    "OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
    "MISTRAL_API_KEY",
    "GOOGLE_GENERATIVE_AI_API_KEY",
    "GEMINI_API_KEY",
    "XAI_API_KEY",
    "GROQ_API_KEY",
    "TOGETHER_API_KEY",
)

_CONFIG_FILENAME = "opencode.json"

# Appended to every prompt so the model returns structured output.
# Phrased to make clear that a text response is required AFTER all tool use —
# models that finish tool-use steps without a text reply produce empty output.
_SCHEMA_INJECTION = (
    "\n\n---\n"
    "After you have finished all tool use, write your final response as plain text "
    "(not via any tool). Your final text must be a single JSON object that exactly "
    "matches the schema below — no markdown fences, no commentary, nothing else:\n"
    + OUTCOME_SCHEMA_STR
)


@contextlib.contextmanager
def _scoped_config(path: Path, content: str) -> Generator[None, None, None]:
    """Write *content* to *path*, yield, then restore or remove it."""
    existed = path.exists()
    original: str | None = path.read_text() if existed else None
    path.write_text(content)
    try:
        yield
    finally:
        if existed and original is not None:
            path.write_text(original)
        elif path.exists():
            path.unlink()


class OpenCodeAgent(Agent):
    """Agent implementation that invokes the opencode CLI subprocess.

    Authentication is handled entirely via provider API keys injected into a
    temporary opencode.json written to the repo working directory. OpenCode
    resolves {env:VAR} placeholders at startup, so no interactive auth is needed.

    Provider → env var convention: {PROVIDER.upper()}_API_KEY.
    Examples: openrouter → OPENROUTER_API_KEY, anthropic → ANTHROPIC_API_KEY.
    Edge cases: google → GOOGLE_GENERATIVE_AI_API_KEY or GEMINI_API_KEY.

    max_turns is not supported; timeout_s is the only bound.
    total_cost_usd is extracted from the step-finish event stream.
    """

    id: ClassVar[str] = "opencode"
    # auth_env_vars is set to the known provider keys so validate_auth can inspect them,
    # but has_auth() always returns True because opencode itself has no mandatory own auth.
    auth_env_vars: ClassVar[tuple[str, ...]] = _KNOWN_PROVIDER_KEYS
    supports_max_turns: ClassVar[bool] = False

    def has_auth(self) -> bool:
        # OpenCode requires no account or license — only a provider API key.
        # Provider keys are validated by validate_auth(); has_auth() is permissive
        # so config loading is not blocked when the key is absent.
        return True

    def validate_auth(self) -> tuple[str, str]:
        if (fail := self.check_binary("opencode")) is not None:
            return fail
        found = [v for v in _KNOWN_PROVIDER_KEYS if os.environ.get(v)]
        if found:
            return (
                "WARN",
                f"opencode: provider key(s) present (not validated): {', '.join(found)}",
            )
        return (
            "WARN",
            "opencode: no known provider API key found — "
            "set e.g. OPENROUTER_API_KEY or ANTHROPIC_API_KEY",
        )

    def invoke(self, prompt: str, config: AgentConfig) -> AgentResult:
        if not self.supports_max_turns:
            _log.debug(
                "opencode: max_turns setting ignored (not supported); bounded by timeout_s only"
            )

        augmented = prompt + _SCHEMA_INJECTION
        cfg_content = _build_config(config)

        # Write opencode.json into the repo working dir so opencode discovers it.
        # config.cwd is the cloned repo root; Labro holds an exclusive lock on it.
        cfg_path = (config.cwd or Path(".")) / _CONFIG_FILENAME

        cmd: list[str] = ["opencode", "run", "--format", "json"]
        if config.provider is not None and config.model is not None:
            cmd += ["--model", f"{config.provider}/{config.model}"]
        if config.effort is not None:
            cmd += ["--variant", config.effort]
        if config.cwd is not None:
            cmd += ["--dir", str(config.cwd)]
        cmd.append(augmented)

        with _scoped_config(cfg_path, cfg_content):
            stdout, stderr = _run_subprocess(cmd, config.timeout_s, config.cwd)

        return _parse_result(stdout, stderr)


# ── helpers ────────────────────────────────────────────────────────────────────


def _build_config(config: AgentConfig) -> str:
    """Build the opencode.json content for *config*."""
    cfg: dict[str, Any] = {
        "$schema": "https://opencode.ai/config.json",
        "permission": {"*": "allow"},
    }
    if config.provider is not None:
        env_var = f"{config.provider.upper()}_API_KEY"
        cfg["provider"] = {config.provider: {"options": {"apiKey": f"{{env:{env_var}}}"}}}
    return json.dumps(cfg, indent=2)


def _run_subprocess(cmd: list[str], timeout_s: int, cwd: Path | None) -> tuple[bytes, bytes]:
    """Run opencode with no stdin; return (stdout, stderr)."""
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=cwd,
        shell=False,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        raise AgentTimeoutError(f"opencode exceeded timeout of {timeout_s}s") from None
    return stdout, stderr


_BENIGN_STDERR_SUBSTRINGS: tuple[str, ...] = (
    "Performing one time database migration",
    "sqlite-migration:",
    "Database migration complete",
)


def _filter_stderr(stderr: bytes) -> str:
    """Return stderr text with known benign opencode startup lines removed."""
    lines = stderr.decode(errors="replace").splitlines()
    filtered = [
        line for line in lines if not any(pat in line for pat in _BENIGN_STDERR_SUBSTRINGS)
    ]
    return "\n".join(filtered).strip()


def _strip_fences(text: str) -> str:
    """Remove leading/trailing markdown code fences if present."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        end = -1 if (len(lines) > 1 and lines[-1].strip() == "```") else None
        text = "\n".join(lines[1:end]).strip()
    return text


def _extract_json_object(text: str) -> Any:
    """Return the last parseable top-level JSON object found in *text*.

    Models sometimes emit reasoning prose before or after the JSON block.
    We scan right-to-left for closing braces and try to parse back to the
    matching opener, returning the first (rightmost) hit.  Falls back to a
    plain json.loads of the whole text if no brace-delimited block matches.

    Raises json.JSONDecodeError if nothing parses.
    """
    # Fast path: whole text is valid JSON.
    stripped = _strip_fences(text)
    try:
        return json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        pass

    # Scan for the last top-level '{...}' block.
    last_close = stripped.rfind("}")
    if last_close == -1:
        raise json.JSONDecodeError("no JSON object found", text, 0)

    search = stripped[: last_close + 1]
    pos = 0
    while True:
        start = search.find("{", pos)
        if start == -1:
            break
        try:
            obj = json.loads(search[start:])
            return obj
        except (json.JSONDecodeError, ValueError):
            pos = start + 1

    raise json.JSONDecodeError("no parseable JSON object found", text, 0)


def _parse_result(stdout: bytes, stderr: bytes) -> AgentResult:
    """Parse the opencode --format json event stream into an AgentResult."""
    text_parts: list[str] = []
    error_messages: list[str] = []
    error_status_codes: list[int] = []
    input_tokens = 0
    output_tokens = 0
    cache_read_tokens = 0
    cache_write_tokens = 0
    total_cost_usd: float | None = None
    seen_types: list[str] = []

    for raw_line in stdout.decode(errors="replace").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            event: dict[str, Any] = json.loads(line)
        except json.JSONDecodeError:
            continue

        evt_type = event.get("type", "")
        seen_types.append(evt_type)
        # Each top-level event wraps its data inside a "part" object.
        part: dict[str, Any] = event.get("part", {})

        if evt_type == "error":
            err = event.get("error", {})
            data = err.get("data", {})
            msg = data.get("message") or err.get("message", "")
            if msg:
                error_messages.append(str(msg))
            # Capture HTTP status codes for quota/billing error detection.
            raw_code = data.get("statusCode")
            if raw_code is not None:
                with contextlib.suppress(TypeError, ValueError):
                    error_status_codes.append(int(raw_code))

        elif evt_type == "text":
            # Collect all text including synthetic (reasoning) blocks.
            # The JSON extraction step below finds the schema-matching object
            # even when reasoning text precedes or follows it.
            text = part.get("text") or event.get("text", "")
            if text:
                text_parts.append(text)

        elif evt_type in ("step-finish", "step_finish"):
            tokens = part.get("tokens", {})
            # Accumulate across steps (opencode reports per-step, not cumulative).
            input_tokens += int(tokens.get("input", 0))
            output_tokens += int(tokens.get("output", 0))
            cache = tokens.get("cache", {})
            cache_read_tokens += int(cache.get("read", 0))
            cache_write_tokens += int(cache.get("write", 0))
            cost = part.get("cost")
            if cost is not None:
                with contextlib.suppress(TypeError, ValueError):
                    total_cost_usd = (total_cost_usd or 0.0) + float(cost)

    raw_text = "".join(text_parts)

    _log.debug("opencode event types seen: %s", seen_types)

    try:
        so = _extract_json_object(raw_text)
    except (json.JSONDecodeError, ValueError) as exc:
        from collections import Counter

        _log.warning(
            "opencode: no parseable text response. Event types seen: %s",
            dict(Counter(seen_types)),
        )
        if stdout:
            _log.warning("opencode stdout (truncated): %s", stdout.decode(errors="replace")[:2000])
        meaningful_stderr = _filter_stderr(stderr)
        if meaningful_stderr:
            _log.warning("opencode stderr: %s", meaningful_stderr[:2000])
        # HTTP 402: provider rejected the request due to insufficient credits.
        # Return a soft failure so the item stays re-queueable rather than
        # being labelled ai-failed.
        if 402 in error_status_codes:
            summary = error_messages[0] if error_messages else "Insufficient credits."
            _log.warning("opencode: provider returned 402 (insufficient credits): %s", summary)
            return AgentResult(
                outcome="failure",
                summary=summary,
                failure_reason="session_limit_hit",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=cache_read_tokens,
                cache_write_tokens=cache_write_tokens,
                total_cost_usd=total_cost_usd,
            )
        agent_error = error_messages[0] if error_messages else None
        raise AgentOutputError(agent_error or f"json_parse_error: {exc}") from None

    try:
        validate_structured_output(so)
    except AgentOutputError as exc:
        raise AgentOutputError(f"opencode structured output invalid: {exc}") from exc

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
        total_cost_usd=total_cost_usd,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
    )
