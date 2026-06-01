# ADR 0006 — Multi-Provider Agent Registry

**Status:** Accepted
**Date:** 2026-06-01

## Context

Labro v1 hardwired Claude Code as its only agent CLI. The `Agent` ABC existed but was never used polymorphically — `ClaudeCodeAgent` was instantiated directly at the call site, all parsing and subprocess logic lived in `runner.py`, and the model slug used a `provider/model@effort` format that assumed only one CLI.

Adding Codex (and future CLIs) requires each agent to own four concerns independently:
1. How CLI arguments are built
2. How it authenticates headless
3. How its response (including errors) maps to `AgentResult`
4. Any other agent-specific logic (e.g. whether `max_turns` is supported)

Codex differs from Claude in every one of these dimensions, proving the abstraction must let each agent own all four.

## Decision

### Slug grammar

CLI-prefixed, clean break (no legacy fallback):

```
<cli>[:<provider>/<model>][@<effort>]
```

The CLI id is the registry key. The `provider` segment is optional metadata (vendor name). `@effort` is always trailing.

Bare legacy slugs (`anthropic/...`) raise `ConfigError` with a helpful migration message. There is no fallback or silent coercion.

**Examples:**
- `claude-code` — CLI default model/effort
- `claude-code:anthropic/claude-opus-4-7@high` — explicit model + effort
- `codex:openai/gpt-5-codex@high` — Codex with explicit model

### Terminology

- **Agent** = the CLI tool / registry key = slug's first segment (`claude-code`, `codex`).
- **Provider** = model vendor = slug's second segment (`anthropic`, `openai`). Optional.

These map 1:1 onto the DB columns `agent`, `provider`, `model`, `effort`.

### Agent registry

A dict keyed by CLI id in `agents/registry.py`. Each agent is a self-contained module owning all four concerns. `get_agent(id)` raises `ValueError` for unknown ids (caller wraps in `ConfigError`).

### Cost / budget

Agents that don't report USD cost (Codex) write `total_cost_usd = NULL`. The daily budget cap (`store.get_daily_spend`) uses `COALESCE(SUM(total_cost_usd), 0)` so NULL rows are skipped. This is a documented gap: Codex runs do not count against the USD budget cap.

### Codex sandbox posture

Inside the hardened container, Labro passes `--dangerously-bypass-approvals-and-sandbox` to Codex so the agent can use `gh` and `git` (network + write access). Per-action enforcement remains at the prompt level, consistent with ADR 0003.

### Auth scoping

`load_config` validates auth only for agents actually referenced by the config (via `referenced_agents()`). A config using only `claude-code` does not require `CODEX_API_KEY`. Auth checking uses `agent.has_auth()` (fast env/file check). The full `validate_auth()` (including HTTP for Claude) is used only in `labro check`.

## Consequences

- Adding a new agent CLI requires: a new module under `agents/`, registration in `agents/registry.py`, and a doc file under `docs/providers/`.
- All model slugs in configs and tests must use the new CLI-prefixed format. Bare `anthropic/...` slugs fail at config load time.
- Codex runs produce `total_cost_usd = NULL` and are excluded from USD budget enforcement.
- Cross-reference: [ADR 0003](0003-prompt-only-action-permissions-enforcement.md) (Codex sandbox bypass rationale).
