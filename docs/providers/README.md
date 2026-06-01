# Agent Providers

Labro supports multiple agent CLIs via its agent registry. Each agent is identified by a **CLI id** (the first segment of the model slug).

## Supported agents

| CLI id | Description | Auth |
|--------|-------------|------|
| `claude-code` | Anthropic Claude Code CLI | `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN` |
| `codex` | OpenAI Codex CLI | `CODEX_API_KEY` or `~/.codex/auth.json` |

## Slug grammar

```
<cli>[:<provider>/<model>][@<effort>]
```

Examples:

| Slug | Agent | Provider | Model | Effort |
|------|-------|----------|-------|--------|
| `claude-code` | claude-code | — | (CLI default) | — |
| `claude-code@high` | claude-code | — | (CLI default) | high |
| `claude-code:anthropic/claude-opus-4-7` | claude-code | anthropic | claude-opus-4-7 | — |
| `claude-code:anthropic/claude-opus-4-7@high` | claude-code | anthropic | claude-opus-4-7 | high |
| `codex:openai/gpt-5-codex@high` | codex | openai | gpt-5-codex | high |

## Per-agent documentation

- [claude-code](claude-code.md) — Anthropic Claude Code CLI
- [codex](codex.md) — OpenAI Codex CLI
