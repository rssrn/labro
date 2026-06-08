# Labro — Autonomous Agent Harness

![Labro](docs/labro_logo.png)

[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue?logo=python&logoColor=white)](pyproject.toml)
[![Docker](https://img.shields.io/github/v/release/rssrn/labro?label=ghcr.io&logo=docker&logoColor=white)](https://github.com/rssrn/labro/pkgs/container/labro)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![mypy: strict](https://img.shields.io/badge/mypy-strict-blue)](https://mypy-lang.org/)
[![bandit](https://img.shields.io/badge/security-bandit-yellow)](https://github.com/PyCQA/bandit)
[![Claude Code](https://img.shields.io/badge/agent-Claude_Code-8A2BE2?logo=anthropic&logoColor=white)](https://claude.ai/code)
[![OpenCode](https://img.shields.io/badge/agent-OpenCode-6366f1)](https://opencode.ai)
[![GitHub](https://img.shields.io/badge/platform-GitHub-181717?logo=github&logoColor=white)](https://github.com)

AI coding agents like Claude Code deliver real productivity gains — but they still demand attention. Labro removes the supervisory overhead: it runs your agent on a cron schedule, picks the highest-priority task from your configured backlog, and records the result — no one needs to be at the keyboard.

**A natural fit for Claude subscribers:** from June 2026, Pro/Max/Team/Enterprise plans include a [monthly pool of headless Agent SDK credits](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan) that expire unused. Labro gives you a concrete, low-risk way to put them to work on your own repos. The harness is deterministic and auditable — it selects a task, constructs a prompt, invokes the agent, records the result, and gets out of the way.

For the full design rationale — why cron instead of webhooks, the autonomy model, and the project philosophy — see [Why Labro](docs/WHY.md).

- **Scheduled, unattended runs** — cron-driven via GitHub Actions or a VPS; no one needs to be at the keyboard
- **Priority-based task picking** — configurable label rules and author rules determine what gets worked on first
- **Flexible deployment** — run as a long-lived VPS container with crond, or as a one-shot container per scheduled GitHub Actions job; both patterns are documented with ready-to-use config
- **Per-project daily spend cap** — set `daily_budget_usd` to hard-stop spending once the limit is reached; the skipped run is recorded so accounting stays accurate
- **Turn-limit handover** — when the agent exhausts its turn budget mid-task, Labro commits any in-progress edits to a `labro-wip/<run-id>` branch, posts a handover comment on the issue with the WIP branch link, and parks the item under `ai-handover` until a human re-queues it — no code is lost and no credits are silently wasted on a retry
- **Graceful failure labelling** — success, partial, and failure outcomes each get distinct GitHub labels so the state of every item is visible at a glance without reading run logs
- **Full audit trail** — every run writes outcome, cost, token usage, and actions to a local SQLite database
- **Emergency pause** — drop a `LABRO_DISABLED` flag file to stop new runs instantly without restarting containers; any run already in progress finishes normally
- **Multi-provider support** — Claude Code, Codex, and OpenCode are all supported; spread scheduled work across providers or use OpenCode to access any model on [models.dev](https://models.dev) (OpenRouter, Anthropic, OpenAI, Mistral, and more). See [Model Selection Guide](docs/MODEL-SELECTION.md) for advice on picking the right model for each task type.

---

There are two ways to run Labro: **Docker** (recommended for production and first-time use) and **local Python** (recommended for development and contributing).

---

## Quickstart — Docker

The `Dockerfile` bundles everything Labro needs: Python 3.12, the `gh` CLI, and a pinned `claude` CLI. This is the recommended way to run Labro in production.

### Prerequisites

- **[Docker](https://docs.docker.com/get-docker/)** (or a compatible runtime such as Podman)
- **GitHub access** — either a **GitHub App** (recommended; bot identity) or a **PAT** (`GH_TOKEN`). See [GitHub Token Setup](docs/DEPLOYMENT.md#github-token-setup) for the full setup guide.
- A **claude CLI auth credential** for live agent runs (not needed for `--dry-run`):
  - **`CLAUDE_CODE_OAUTH_TOKEN`** (recommended) — OAuth token tied to your Claude subscription (Pro/Max). Generate once with `claude setup-token` on your dev machine.
  - **`ANTHROPIC_API_KEY`** (untested) — standard Anthropic API key; bills your API account. If both vars are set, this takes precedence over the OAuth token.

### 1. Clone and build

```bash
git clone https://github.com/rssrn/labro.git
cd labro
docker build --target base -t labro:latest .
```

> **Build targets:** `--target base` (production) omits the test suite and dev extras. Omit `--target` for the `dev` stage, which includes `tests/` — useful for CI and contributors. `labro:latest` is the production tag by convention.

**ARM64 / Oracle Cloud Ampere A1:** the image is arch-aware. Build natively on the instance, or cross-build from an amd64 host with:

```bash
docker buildx build --target base --platform linux/arm64 -t labro:arm64 .
```

### 2. Write a minimal `labro.toml`

```toml
[digest]
enabled = false

[defaults]
model = "anthropic/claude-sonnet-4-6"

[[projects]]
name       = "my-project"
repo       = "my-org/my-repo"
cron       = "0 * * * *"

[[projects.task_sources]]
type = "gh-label"

[[projects.task_sources.label_rules]]
label             = "ai-dev"
done_label        = "ai-dev-done"
permitted_actions = ["comment_on_issue", "open_pr"]
```

### 3. Dry-run

Verify Labro resolves a task, agent config, and full prompt against your real repo — no tokens spent, no writes, no side effects:

```bash
docker run --rm \
  -e GH_TOKEN=<your-github-token> \
  -v "$PWD/labro.toml:/data/labro.toml:ro" \
  labro:latest run my-project --dry-run
```

### 4. Pre-flight check and label setup

Run `labro check` to validate your config, environment variables, GitHub token connectivity, and that all required labels exist:

```bash
docker run --rm \
  -e GH_TOKEN=<your-github-token> \
  -e CLAUDE_CODE_OAUTH_TOKEN=<your-token> \
  -v "$PWD/labro.toml:/data/labro.toml:ro" \
  labro:latest check
```

Each line of output is prefixed with `OK  `, `WARN`, or `FAIL`. Fix any `FAIL` items before proceeding. `WARN` items (such as the OAuth token check) are informational — Labro will still run.

If labels are missing, create them with `labro init`:

```bash
docker run --rm \
  -e GH_TOKEN=<your-github-token> \
  -v "$PWD/labro.toml:/data/labro.toml:ro" \
  labro:latest init
```

This creates every label referenced in `labro.toml` across all configured repos using `gh label create --force` (idempotent — safe to re-run).

### 5. Validate the `claude` CLI (before live runs)

Before running Labro with a live agent, confirm `claude -p` works inside the container:

```bash
docker run --rm \
  --entrypoint sh \
  -e CLAUDE_CODE_OAUTH_TOKEN=<your-token> \
  labro:latest \
  -c 'echo "hello" | claude -p --output-format json'
```

The response should contain top-level `type`, `is_error`, and `result` fields. If it fails with an auth error requiring interactive login, resolve the container auth strategy before proceeding to live runs.

> **Note:** if both `CLAUDE_CODE_OAUTH_TOKEN` and `ANTHROPIC_API_KEY` are set, `ANTHROPIC_API_KEY` takes precedence and bills your API account.

For production deployment options (GitHub Actions, VPS with crond, config repo), see the [Deployment Guide](docs/DEPLOYMENT.md).

---

## Quickstart — local development

Use this path if you want to contribute, run the test suite, or iterate quickly without rebuilding the image.

### Prerequisites

- **Python 3.12+**
- **[uv](https://docs.astral.sh/uv/)** — fast Python package manager (`pip install uv` or see the uv docs)
- **[gh](https://cli.github.com/)** — GitHub CLI, authenticated (`gh auth login`)

### 1. Clone and create the virtual environment

```bash
git clone https://github.com/rssrn/labro.git
cd labro
uv venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
```

### 2. Install dependencies

```bash
uv pip install -e '.[dev]'
```

This installs Labro in editable mode along with all dev tools: ruff, mypy, bandit, pytest, pip-audit, and pre-commit.

### 3. Install pre-commit hooks

```bash
pre-commit install
```

Hooks run automatically on `git commit` (ruff, mypy-strict, bandit, shellcheck, check-toml, pytest) and on `git push` (pip-audit).

### 4. Run the test suite

```bash
pytest
```

### 5. First dry-run

Create a `labro.toml` as shown in the Docker quickstart above, then:

```bash
export GH_TOKEN=<your-github-token>
labro run my-project --dry-run
```

Labro will print the resolved task, agent config, and full four-section prompt to stdout.

---

## Proactive Improvement

The `proactive-improvement` task source triggers when the picker reaches it in the configured priority list. Labro creates a tracking issue, then asks the agent to investigate and post findings as a comment.

### Minimal config

```toml
[[projects.task_sources]]
type = "proactive-improvement"
permitted_actions = ["comment_on_issue", "open_pr"]
```

### All options

```toml
[[projects.task_sources]]
type                 = "proactive-improvement"
max_open_suggestions = 3              # skip if this many open ai-proactive-suggestion issues exist
perspectives         = []             # names from perspectives.toml; empty = use all
persona              = "senior-dev"   # optional persona (defined in [personas])
permitted_actions    = ["comment_on_issue", "open_pr"]
model                = "claude-code:anthropic/claude-sonnet-4-6@high"
```

### Perspectives

A **perspective** is a prompt lens that shapes the agent's approach for a single proactive run. Copy `perspectives.toml` from the repo root alongside your `labro.toml` and edit it to suit your project. Labro picks one at random each time the source fires, and records the chosen perspective in the `runs` table for auditability.

See [Proactive Improvement — Perspectives](docs/OPERATIONS.md#proactive-improvement--perspectives) for the full configuration reference.

---

## Metrics Dashboard

**Live example:** [labro.rossarnold.uk](https://labro.rossarnold.uk/)

> **⚠️ Data sensitivity:** the published snapshot contains private-repo prose — task descriptions, summaries, failure reasons, and item URLs from your monitored repositories. The dashboard ships **no built-in access control**. The bucket URL is the only barrier. Keep it private: do not share it, embed it in public pages, or link to it from anywhere indexable. See [ADR-0007](docs/adr/0007-metrics-dashboard.md) for the accepted risk posture and the deferred Cloudflare Access / column-redaction options.

The dashboard is a read-only static SPA (React + Vite + sql.js) served from Cloudflare R2. It loads a published snapshot of `labro.db` client-side and renders a runs list, per-project stats, and charts. It has no runtime link to the harness and cannot affect runs.

### 1. Create an R2 bucket and bind a custom domain

In the Cloudflare dashboard, create an R2 bucket, then generate an S3 API token scoped to it (Account → R2 → Manage R2 API tokens). Note the access key ID, secret key, and your Cloudflare account ID.

Bind a **custom domain** to the bucket (bucket → Settings → Custom Domains). The SPA, `/manifest.json`, and `/db/*.db` must share the same origin so DB fetches are same-origin and no CORS headers are needed.

### 2. Configure `[dashboard]` in `labro.toml`

```toml
[dashboard]
enabled    = true
bucket     = "my-labro-dashboard"   # R2 bucket name
key_prefix = ""                     # optional path prefix inside the bucket
cron       = "17 * * * *"           # snapshot publish frequency
```

When `enabled = true`, `labro gen-crontab` emits a `labro publish-db` cron line automatically and `labro check` validates the three `R2_*` env vars.

### 3. Set R2 credentials

Add `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, and `R2_ACCOUNT_ID` to:
- the VPS `.env` file (see [Config Repo](docs/DEPLOYMENT.md#config-repo))
- your config-repo GitHub Secrets (for the `dashboard-publish.yml` workflow)

### 4. Publish the first snapshot

```bash
labro publish-db --dry-run   # prints hashed db_key + manifest JSON; no upload, no creds required
labro publish-db             # uploads snapshot to R2 (db first, then manifest)
```

After the first successful upload, `manifest.json` and `db/labro-<hash>.db` appear in the R2 bucket.

### 5. Deploy the SPA

Copy `docs/config-repo-scaffold/dashboard-publish.yml` into `.github/workflows/` in your config repo and add the four R2 secrets. Push to trigger the first build and upload. Once deployed, open your custom domain — the dashboard loads data from the published snapshot.

The SPA rebuilds automatically when `dashboard/**` changes on labro `main` (dispatched via `dashboard-dispatch.yml`). Snapshot publishing runs independently on the cron in `[dashboard]`.

---

## Documentation

- **[Why Labro](docs/WHY.md)** — design rationale: why cron not webhooks, the autonomy model, and the project philosophy.
- **[Deployment Guide](docs/DEPLOYMENT.md)** — GitHub token setup, Docker deployment modes (GitHub Actions and VPS), graceful restart procedure, and config-repo workflow.
- **[Operations Reference](docs/OPERATIONS.md)** — live run loop internals, environment variables, label transitions, turn-limit handling, daily budget cap, signal collection, and CLI reference.
- **[Model Selection Guide](docs/MODEL-SELECTION.md)** — advice on choosing agents and models per task type, with cost-shaping strategies and caveats.
- **[Architecture](docs/ARCHITECTURE.md)** — system context, component design, runtime flow, and architectural decisions.
- **[Product Requirements Document](docs/PRD.md)** — problem statement, design principles, functional requirements, and success metrics.
- **[Roadmap](docs/ROADMAP.md)** — delivery milestones and per-file completion tracking.
- **[Architectural Decision Records](docs/adr/)** — record of significant design decisions.
- **[Domain Glossary](CONTEXT.md)** — canonical definitions for terms used across all Labro documents and code.

---

## Development

The full quality-gate toolchain is installed with `uv pip install -e '.[dev]'`:

| Tool | Purpose |
|---|---|
| `ruff` | Linting and formatting — `uv run ruff check .` / `uv run ruff format .` |
| `mypy` | Type checking in strict mode — `uv run mypy src/` |
| `bandit` | Security linting — `uv run bandit -r src/` |
| `pytest` | Test suite with 80% coverage floor — `uv run pytest` |
| `pre-commit` | Hooks: ruff, mypy, bandit, shellcheck, pytest on commit; pip-audit on push |

**Before every commit:** run `uv run ruff format .` — the pre-commit hook aborts and reformats if you skip it, requiring a second commit attempt.

## Testing

```bash
uv run pytest            # full test suite
uv run pytest -x         # stop on first failure
uv run pytest -k name    # run tests matching a name
```

Tests live in `tests/`. The coverage floor is 80% — new code should be covered.

## Contributing

1. Fork the repo and create a feature branch.
2. Follow the quality gates: ruff, mypy strict, bandit (no `shell=True` — B602 must not be skipped), and 80% test coverage.
3. Open a PR against `main` with a clear description of what and why.

The harness is deliberately dumb — if you're adding intelligence, it probably belongs in a prompt, not the codebase. Read [Architecture](docs/ARCHITECTURE.md) and the [ADRs](docs/adr/) before adding abstractions.

## Security

The `bandit` B602 rule (`shell=True`) must never be skipped — all subprocess calls use list form. Report security vulnerabilities privately via [GitHub Security Advisories](https://github.com/rssrn/labro/security/advisories/new).

## License

Apache-2.0 — see [LICENSE](LICENSE).
