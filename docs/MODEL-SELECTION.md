# Model Selection Guide

Labro lets you configure which agent and model to use at multiple levels, from global defaults down to individual label rules.

## Caveats

- **Models change fast.** A model that works well today may be deprecated, rate-limited, or replaced by a better/cheaper option tomorrow. This guide reflects the landscape at the time of writing — re-evaluate periodically.
- **Labro is model-agnostic.** The harness does not prefer or endorse any specific provider or model. Examples are illustrative, not recommendations. Your choice is yours.
- **Your data, your risk.** Models accessed via free/public endpoints (or any provider whose terms allow training on API inputs) may use your prompts and repo contents for model training. If your repository contains sensitive code, business logic, or credentials, factor this into your model choice. Paid API tiers typically offer stronger data privacy guarantees — check each provider's terms.
- **Cost is not quality.** A more expensive model is not always better for every task. Matching model capability to task complexity is the skill this guide is meant to help with.

---

## Model slug format

```
<cli>[:<provider>/<model>][@<effort>]
```

| Part | Required | Meaning |
|------|----------|---------|
| `<cli>` | yes | Agent CLI: `claude-code`, `codex`, or `opencode` |
| `<provider>` | no | Vendor: `anthropic`, `openai`, `openrouter`, etc. |
| `<model>` | no | Model name (e.g. `claude-opus-4-7`, `gpt-5-codex`) |
| `@<effort>` | no | Reasoning budget: `low`, `medium`, `high`, `max` |

**Examples:**

| Slug | CLI | Provider | Model | Effort |
|------|-----|----------|-------|--------|
| `claude-code` | claude-code | — | (CLI default) | — |
| `claude-code:anthropic/claude-opus-4-7@max` | claude-code | anthropic | claude-opus-4-7 | max |
| `codex:openai/gpt-5-codex` | codex | openai | gpt-5-codex | — |
| `opencode:openrouter/openai/gpt-oss-120b:free` | opencode | openrouter | openai/gpt-oss-120b:free | — |
| `opencode:opencode/big-pickle` | opencode | opencode | big-pickle | — |
| `opencode:opencode/nemotron-3-super-free` | opencode | opencode | nemotron-3-super-free | — |

See `docs/providers/` for per-agent documentation.

---

## Resolution order

The effective model for a run is resolved at config-load time with this precedence (highest first):

1. **Label rule** (in `gh-label` or `gh-author` source) — most specific
2. **Task source** (e.g. `grafana-alerts`, `proactive-improvement`)
3. **Project-level** (`[projects]`)
4. **Global default** (`[defaults]`)

```toml
[defaults]
model = "opencode:openrouter/openai/gpt-oss-120b:free"  # cheap fallback for everything

[[projects]]
name  = "my-api"
repo  = "owner/my-api"
model = "claude-code:anthropic/claude-sonnet-4-6@high"  # project-level upgrade

  [[projects.task_sources]]
  type = "gh-label"

    [[projects.task_sources.label_rules]]
    rule  = "analyst"  # inherits project default (claude-sonnet-4-6)

    [[projects.task_sources.label_rules]]
    rule  = "dev"
    model = "claude-code:anthropic/claude-opus-4-7@max"  # override for complex work

    [[projects.task_sources.label_rules]]
    rule  = "dependabot-routine"
    model = "opencode:opencode/big-pickle"  # different agent entirely

[[projects.task_sources]]
type         = "grafana-alerts"
model        = "claude-code:anthropic/claude-opus-4-7@high"  # prod alerts
```

A model set at a lower level (e.g. on a label rule) completely replaces the inherited value — there is no deep merge of individual slug components. If you set `model = "codex:openai/gpt-5-codex"` on a rule, it uses Codex, not Claude Code.

---

## Which agent CLI?

### `claude-code` (default)

**Pros:** Native structured output via `--json-schema`, subcommand-level `--allowedTools` for fine-grained permissions, `--max-turns` support, reliable USD cost reporting, best model for complex reasoning.

**Cons:** Requires Anthropic API key or Claude subscription OAuth token. Models: Opus (most capable/expensive), Sonnet (balanced), Haiku (fast/cheap).

**Best for:** Everything, unless you have a specific reason to use something else.

### `opencode`

**Pros:** Provider-agnostic — route through OpenRouter, Anthropic, OpenAI, Mistral, Groq, etc. Access models not on Anthropic's API (e.g. Qwen3, DeepSeek, GPT-5). No account or license required.

**Cons:** No `--max-turns`, structured output is prompt-injected (less reliable), coarser permission model, cost reporting depends on provider.

**Best for:** Routing to cheaper third-party models for low-stakes work, or when you want to compare models without switching CLIs.

### `codex`

**Pros:** OpenAI's coding agent, good for tasks where OpenAI models work best.

**Cons:** No `--max-turns`, no USD cost reporting, OpenAI API key required.

**Best for:** Experimentation or when your workflow is already OpenAI-centric.

---

## Effort / reasoning budget

Not all agents support effort levels the same way. `claude-code` maps `@effort` to its `--effort` flag, while `opencode` maps it to `--variant`.

| Level | When to use | Typical tasks |
|-------|-------------|---------------|
| `low` | Trivial, deterministic work | Dependabot review comments, label-only triage |
| `medium` | Routine tasks with clear scope | Bug triage, simple PR review, test coverage review |
| `high` | Complex or open-ended reasoning | Feature implementation, architecture review, alert investigation |
| `max` | Maximum reasoning budget | Hard bugs, security review, architectural decisions |

---

## Task-specific recommendations

### `gh-label` / `gh-author` — labelled issues and PRs

Match model capability to the label's implied complexity:

| Label type | Recommended model | Rationale |
|------------|-------------------|-----------|
| Dev work (feature, bugfix) | `claude-code:anthropic/claude-opus-4-7@max` | Needs to write code; max reasoning pays for itself |
| Architecture review | `claude-code:anthropic/claude-sonnet-4-6@medium` | Design discussion, not implementation |
| Business analysis | `opencode:opencode/big-pickle` | Comment-only; no need for expensive reasoning |
| Dependabot security | `claude-code:anthropic/claude-sonnet-4-6@high` | Security matters, but scope is narrow |
| Dependabot routine | `opencode:opencode/big-pickle` | Comment-only; cheapest option works |
| Free-tier proactive | `opencode:opencode/nemotron-3-super-free` | Zero-cost exploration when nothing urgent is queued |

### `grafana-alerts` — production alert triage

Production alerts warrant a capable model — cost is secondary to correctness. If you can't or don't want to use Claude Code, route through opencode to your provider of choice:

```toml
model = "claude-code:anthropic/claude-opus-4-7@high"
# or
model = "opencode:anthropic/claude-opus-4-7@high"
```

If latency matters, keep effort at `high` rather than `max` — the marginal gain from max is small for triage and the extra thinking time delays the response.

### `proactive-improvement` — open-ended exploration

Proactive suggestions are a good place to use free or cheap models since the work is optional and best-effort:

```toml
model = "opencode:opencode/nemotron-3-super-free"
```

Or use a capable model for deeper analysis:

```toml
model = "claude-code:anthropic/claude-opus-4-7@high"
```

---

## Cost shaping strategies

### 1. Set a cheap global default, override upwards

```toml
[defaults]
model = "opencode:openrouter/openai/gpt-oss-120b:free"
```

Then upgrade to better models only where needed (dev work, alerts).

### 2. Route Dependabot PRs and analyst work through cheap models

```toml
model = "opencode:opencode/big-pickle"
```

### 3. Use effort levels to cap reasoning spend on Claude Code

A `claude-opus-4-7@low` run costs less than `claude-sonnet-4-6@high` while still having Opus-level knowledge.

### 4. Run with `--dry-run` first

Before committing to a model for a task type, inspect the task description and prompt with `labro run <project> --dry-run` to verify the scope matches the model's capability.

---

## Slug reference

Quick-reference table of valid slug components (not exhaustive).

### Agents

| CLI id | Provider slugs | Common models |
|--------|----------------|---------------|
| `claude-code` | `anthropic` | `claude-opus-4-7`, `claude-sonnet-4-6`, `claude-haiku-4-5-20251001` |
| `codex` | `openai` | `gpt-5-codex` |
| `opencode` | `openrouter`, `opencode`, `anthropic`, `openai`, `mistral`, `xai`, `groq` | Provider-specific; check [models.dev](https://models.dev). Examples: `openai/gpt-oss-120b:free`, `opencode/big-pickle`, `opencode/nemotron-3-super-free` |

### Effort

Only `claude-code` and `opencode` support effort levels. Codex ignores `@effort`.

`@low`, `@medium`, `@high`, `@max`

---

## Limitations by agent

| Feature | claude-code | codex | opencode |
|---------|-------------|-------|----------|
| `--max-turns` support | Yes | No | No |
| USD cost reporting | Yes | No | Depends on provider |
| Structured output | Native (`--json-schema`) | File-based | Prompt-injected |
| Fine-grained tool permissions | Yes (`--allowedTools`) | No (sandbox bypass) | No (tool-level only) |

Check `docs/providers/*.md` for full details on each agent.
