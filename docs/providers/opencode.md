# opencode — OpenCode AI coding agent

[OpenCode](https://opencode.ai) is a provider-agnostic terminal AI agent. Labro uses it as an
alternative to Claude Code and Codex when you want to route work through OpenRouter,
Anthropic's API, OpenAI, Mistral, or any other provider supported by [models.dev](https://models.dev).

## Install

OpenCode ships as a standalone binary — no Node.js required.

```bash
# amd64
curl -fsSL https://github.com/anomalyco/opencode/releases/download/v1.15.13/opencode-linux-x64.tar.gz \
  | tar -xzO > /usr/local/bin/opencode && chmod +x /usr/local/bin/opencode

# arm64
curl -fsSL https://github.com/anomalyco/opencode/releases/download/v1.15.13/opencode-linux-arm64.tar.gz \
  | tar -xzO > /usr/local/bin/opencode && chmod +x /usr/local/bin/opencode
```

The Labro Docker image installs opencode automatically from the same release tarball
(pinned via `OPENCODE_VERSION` in the `Dockerfile`).

## Headless auth

OpenCode itself requires no account or license. Authentication is per-provider and is
handled via a temporary `opencode.json` config file that Labro writes to the repo working
directory before each run. The file uses opencode's `{env:VAR}` interpolation so the API key
is never stored on disk.

### Provider → env var mapping

Labro derives the env var name as `{PROVIDER.upper()}_API_KEY`:

| Provider slug | Env var |
|---|---|
| `openrouter` | `OPENROUTER_API_KEY` |
| `anthropic` | `ANTHROPIC_API_KEY` |
| `openai` | `OPENAI_API_KEY` |
| `mistral` | `MISTRAL_API_KEY` |
| `xai` | `XAI_API_KEY` |
| `groq` | `GROQ_API_KEY` |

For Google providers use `GOOGLE_GENERATIVE_AI_API_KEY` or `GEMINI_API_KEY` (whichever your
account uses); set the correct env var explicitly and reference it in your own global
`~/.config/opencode/config.json` if the derived name doesn't match.

**Example** — inject as a Docker secret:

```bash
docker run -e OPENROUTER_API_KEY=sk-or-... labro run myproject
```

`labro check` reports a `WARN` if no known provider key is set in the environment. This is a
warning, not a hard failure — Labro will attempt the run and opencode will surface the auth
error at runtime.

## Example slugs

```toml
# Defaults section or per-project / per-rule override:
model = "opencode:openrouter/qwen/qwen3-coder-480b-a35b"
model = "opencode:openrouter/qwen/qwen3-coder-480b-a35b@high"
model = "opencode:anthropic/claude-opus-4-7"
model = "opencode:openai/gpt-4o"
```

The `provider/model` component is passed directly to opencode's `--model` flag and must
match a valid models.dev identifier for the chosen provider.

## Effort

The `@effort` slug suffix (e.g. `@high`) is passed to opencode as `--variant`. Available
variants are model-specific — consult the provider's documentation or models.dev.

## Permissions

Labro writes a `opencode.json` with `"permission": {"*": "allow"}` before each run so
opencode auto-approves all tool calls. Per-action enforcement remains at the prompt level
(via `permitted_actions` in `labro.toml`) following the same approach as other agents.

## Limitations

- **No `--max-turns` equivalent**: `max_turns` config is ignored; the run is bounded only by
  `timeout_s`.
- **No USD cost reporting from the API**: `total_cost_usd` is extracted from opencode's
  `step-finish` event stream. If opencode doesn't emit cost data for a provider, it will be
  `NULL` in the runs table. Daily budget caps may not work for those providers.
- **Coarse permission model**: opencode's tool permissions are tool-level only (`bash: allow`),
  not subcommand-level like Claude Code's `--allowedTools`. Labro relies on prompt-level
  constraints for fine-grained action control.
- **Structured output via prompt injection**: opencode has no native `--json-schema` CLI flag.
  Labro appends the expected JSON schema to the prompt and parses the model's text response.
  The model may occasionally wrap the JSON in markdown fences (stripped automatically) or
  include commentary (causes a `failure` outcome with the raw text logged for debugging).
