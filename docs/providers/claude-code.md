# claude-code — Anthropic Claude Code CLI

## Install

```bash
npm install -g "@anthropic-ai/claude-code@<version>"
```

The Dockerfile pins a specific version to prevent silent response-shape drift.

## Headless auth

Two auth modes are supported; the CLI honours whichever is set:

| Method | Env var | Billing | Validate |
|--------|---------|---------|---------|
| API key | `ANTHROPIC_API_KEY` | Anthropic API (pay-as-you-go) | `GET /v1/models` (no tokens) |
| OAuth token | `CLAUDE_CODE_OAUTH_TOKEN` | Claude subscription (Pro/Max) | `labro check` warns "not validated" |

Generate an OAuth token once with `claude setup-token`.

## Example slug

```toml
model = "claude-code:anthropic/claude-opus-4-7@high"
```

## Model options

Any model available via the Anthropic API, e.g.:
- `claude-opus-4-7` — most capable
- `claude-sonnet-4-6` — balanced
- `claude-haiku-4-5-20251001` — fastest/cheapest

## Effort options

`low`, `medium`, `high`, `max` — maps to `--effort` flag.

## Limitations

- Requires GitHub auth (`GH_TOKEN` PAT, or `GH_APP_PRIVATE_KEY` for GitHub App auth) for the `gh` CLI calls the agent makes.
- `--max-turns` is supported and enforced.
- USD cost is reported per run (`total_cost_usd`).
