# codex — OpenAI Codex CLI

## Install

```bash
npm install -g "@openai/codex@<version>"
```

## Headless auth

Two auth modes are supported:

| Method | Credential | Billing | Notes |
|--------|-----------|---------|-------|
| API key | `CODEX_API_KEY` env var | OpenAI Platform pay-as-you-go | Recommended for Docker |
| OAuth | `~/.codex/auth.json` | ChatGPT subscription budget | Requires initial browser flow |

**API key path** (recommended):
- Inject `CODEX_API_KEY` as a Docker/runtime secret.
- Billed against the OpenAI Platform wallet (platform.openai.com/settings/organization/usage).
- No free tier.

**OAuth path** (access free/subscription budget):
- Run `codex auth login` once to authenticate interactively; writes `~/.codex/auth.json` on your dev machine.
- The Labro container runs as root, so the CLI expects the file at `/root/.codex/auth.json` inside the container.
- Mount it as a Docker secret or bind-mount at runtime:
  ```
  docker run ... -v $HOME/.codex/auth.json:/root/.codex/auth.json:ro labro
  ```
- Do **not** bake `auth.json` into a public image — it contains plaintext access tokens.
- Codex CLI refreshes tokens automatically on each run.
- `labro check` validates presence (WARN) but cannot verify the token without spending tokens.

> **Note:** `CODEX_API_KEY` is the correct env var. `OPENAI_API_KEY` is not recognised by the
> Codex CLI out of the box (it requires a custom `config.toml` provider block).

## Example slug

```toml
model = "codex:openai/gpt-5-codex@high"
```

## Effort options

Passed as `-c model_reasoning_effort=<effort>` (e.g. `high`).

## Limitations

- **No `--max-turns` equivalent**: `max_turns` config is ignored; the run is bounded only by `timeout_s`.
- **No USD cost reporting**: `total_cost_usd` is always `NULL` in the runs table. Daily budget caps sum only runs with a reported cost (documented gap — see ARCHITECTURE §11).
- **Sandbox bypass**: Labro always passes `--dangerously-bypass-approvals-and-sandbox` so the agent can use `gh` and `git` (requires network + write access inside the container). Per-action enforcement remains at the prompt level per ADR 0003.
- Structured output is delivered via `--output-schema` + `-o` (a temp file), not Claude's inline `structured_output` field.
