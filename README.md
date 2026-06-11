# Labro — Autonomous Agent Harness

![Labro](docs/labro_logo.png)

[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue?logo=python&logoColor=white)](pyproject.toml)
[![Docker](https://img.shields.io/github/v/release/rssrn/labro?label=ghcr.io&logo=docker&logoColor=white)](https://github.com/rssrn/labro/pkgs/container/labro)
[![Python CI](https://github.com/rssrn/labro/actions/workflows/ci-python.yml/badge.svg)](https://github.com/rssrn/labro/actions/workflows/ci-python.yml)
[![Dashboard CI](https://github.com/rssrn/labro/actions/workflows/ci-dashboard.yml/badge.svg)](https://github.com/rssrn/labro/actions/workflows/ci-dashboard.yml)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![mypy: strict](https://img.shields.io/badge/mypy-strict-blue)](https://mypy-lang.org/)
[![bandit](https://img.shields.io/badge/security-bandit-yellow)](https://github.com/PyCQA/bandit)
[![Claude Code](https://img.shields.io/badge/agent-Claude_Code-8A2BE2?logo=anthropic&logoColor=white)](https://claude.ai/code)
[![OpenCode](https://img.shields.io/badge/agent-OpenCode-6366f1)](https://opencode.ai)
[![GitHub](https://img.shields.io/badge/platform-GitHub-181717?logo=github&logoColor=white)](https://github.com)

**Labro runs AI coding agents on a schedule so you don't have to watch them.**

See [Why Labro](docs/WHY.md) for the design rationale: why supervision is the bottleneck, why scheduled complements event-driven, and why the harness stays simple.  [Live dashboard →](https://labro.rossarnold.uk/)

- **Runs on a schedule** — cron-driven via GitHub Actions or a dedicated server; no one needs to be at the keyboard
- **Picks the right task from your GitHub Issues backlog** — you define label and author rules that determine priority
- **Safeguards** — daily budget cap, model fallback on failure, and configurable tool-use restrictions
- **Full audit trail** — every run records outcome, cost, tokens, and actions to a local SQLite database

---

There are two ways to run Labro: **Docker** (recommended for production and first-time use) and **local Python** (recommended for development and contributing).

---

## Quickstart — Docker

The `Dockerfile` bundles everything Labro needs: Python 3.12, the `gh` CLI, and the `claude` and `opencode` CLIs. This is the recommended way to run Labro in production.

> **💡 Tip for Claude subscribers:** from June 2026, Pro/Max/Team/Enterprise plans include a [monthly pool of headless Agent SDK credits](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan) that expire unused. Labro gives you a concrete, low-risk way to put them to work on your own repos.

### Prerequisites

- **[Docker](https://docs.docker.com/get-docker/)** (or a compatible runtime such as Podman)
- **GitHub access** — either a **GitHub App** (recommended; bot identity) or a **PAT** (`GH_TOKEN`). See [GitHub Token Setup](docs/DEPLOYMENT.md#github-token-setup) for the full setup guide.
- **An agent credential** for live runs (not needed for `--dry-run`) — pick one based on which provider you plan to use:
  - **`CLAUDE_CODE_OAUTH_TOKEN`** — OAuth token for Claude Code (Pro/Max subscription). Generate once with `claude setup-token` on your dev machine.
  - **`OPENAI_API_KEY`** — API key for OpenAI Codex (`codex:openai/...` models).
  - **`OPENCODE_*` / provider key** — OpenCode supports any model on [models.dev](https://models.dev) (OpenRouter, Anthropic, Mistral, and more); see the [Model Selection Guide](docs/MODEL-SELECTION.md) for per-provider env vars.

  See [Deployment Guide](docs/DEPLOYMENT.md#agent-credentials) for the full list of supported env vars and precedence rules.

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
[defaults]
model = "claude-code:anthropic/claude-sonnet-4-6"   # or an array for fallback: ["slug1", "slug2"]

[[projects]]
name       = "my-project"
repo       = "my-org/my-repo"
cron       = "0 * * * *"             # hourly; consumed by `labro gen-crontab` for scheduling

[[projects.task_sources]]
type = "gh-label"

[[projects.task_sources.label_rules]]
label             = "ai-dev"
done_label        = "ai-dev-done"
permitted_actions = ["comment_on_issue", "open_pr"]
```

The `cron` field tells `labro gen-crontab` how often to schedule each project. The container does not schedule itself — that's covered at the end of this section.

### 3. Create the labels and a test issue

Create the labels Labro expects in your repo:

```bash
docker run --rm \
  -e GH_TOKEN=<your-github-token> \
  -v "$PWD/labro.toml:/data/labro.toml:ro" \
  labro:latest init
```

This runs `gh label create --force` for every label in `labro.toml` (idempotent — safe to re-run).

Then open a real issue in `my-org/my-repo` and apply the `ai-dev` label to it. Labro picks tasks from live GitHub issues — without a labelled issue, the picker finds nothing and later steps will show "no task found."

### 4. Pre-flight check

Run `labro check` to validate your config, environment variables, and GitHub token connectivity:

```bash
docker run --rm \
  -e GH_TOKEN=<your-github-token> \
  -e <YOUR_AGENT_CREDENTIAL>=<value> \
  -v "$PWD/labro.toml:/data/labro.toml:ro" \
  labro:latest check
```

Replace `<YOUR_AGENT_CREDENTIAL>` with whichever var your provider uses (e.g. `CLAUDE_CODE_OAUTH_TOKEN`, `OPENAI_API_KEY`). Each output line is prefixed with `OK  `, `WARN`, or `FAIL` — fix any `FAIL` items before continuing.

### 5. Dry-run

Verify Labro resolves the test issue, builds the full prompt, and selects the right agent — no tokens spent, no writes, no side effects:

```bash
docker run --rm \
  -e GH_TOKEN=<your-github-token> \
  -v "$PWD/labro.toml:/data/labro.toml:ro" \
  labro:latest run my-project --dry-run
```

You should see the resolved task, agent config, and four-section prompt printed to stdout.

### 6. Validate your agent CLI

Before the first live run, confirm the agent CLI authenticates correctly inside the container. Example for Claude Code:

```bash
docker run --rm \
  --entrypoint sh \
  -e CLAUDE_CODE_OAUTH_TOKEN=<your-token> \
  labro:latest \
  -c 'echo "hello" | claude -p --output-format json'
```

The response should contain top-level `type`, `is_error`, and `result` fields. If it fails with an auth error requiring interactive login, resolve the container auth strategy before proceeding.

For Codex or OpenCode validation steps, see [Deployment Guide — Agent Credentials](docs/DEPLOYMENT.md#agent-credentials).

### 7. Live run

Run Labro against the test issue:

```bash
docker run --rm \
  -e GH_TOKEN=<your-github-token> \
  -e <YOUR_AGENT_CREDENTIAL>=<value> \
  -v "$PWD/labro.toml:/data/labro.toml:ro" \
  -v labro-data:/data \
  labro:latest run my-project
```

The `-v labro-data:/data` named volume persists `labro.db` (the run audit trail) across invocations. Labro will pick the test issue, invoke the agent, post a comment or open a PR, and transition the label from `ai-dev` to `ai-dev-done`.

**Next step — scheduling:** a one-shot `docker run` is enough for testing, but production use means running on a schedule. See the [Deployment Guide](docs/DEPLOYMENT.md) for GitHub Actions cron, a dedicated server with crond, and config-repo patterns.

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

A read-only static SPA (React + Vite + sql.js) served from Cloudflare R2. It loads a published snapshot of `labro.db` client-side and renders a runs list, per-project stats, and charts — no runtime link to the harness.

> **⚠️ Data sensitivity:** the published snapshot contains private-repo prose. The dashboard ships **no built-in access control**. The bucket URL is the only barrier. Keep it private. See [ADR-0007](docs/adr/0007-metrics-dashboard.md).

Full setup guide: [Metrics Dashboard](docs/DASHBOARD.md)

---

## Documentation

- **[Why Labro](docs/WHY.md)** — design rationale: why cron not webhooks, the autonomy model, and the project philosophy.
- **[Deployment Guide](docs/DEPLOYMENT.md)** — GitHub token setup, Docker deployment modes (GitHub Actions and a dedicated server), graceful restart procedure, and config-repo workflow.
- **[Operations Reference](docs/OPERATIONS.md)** — live run loop internals, environment variables, label transitions, turn-limit handling, daily budget cap, signal collection, and CLI reference.
- **[Model Selection Guide](docs/MODEL-SELECTION.md)** — advice on choosing agents and models per task type, with cost-shaping strategies and caveats.
- **[Architecture](docs/ARCHITECTURE.md)** — system context, component design, runtime flow, and architectural decisions.
- **[Metrics Dashboard](docs/DASHBOARD.md)** — R2 bucket setup, `[dashboard]` config, snapshot publishing, and SPA deployment.
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

The harness is deliberately simple — if you're adding intelligence, it probably belongs in a prompt, not the codebase. Read [Architecture](docs/ARCHITECTURE.md) and the [ADRs](docs/adr/) before adding abstractions.

## Security

The `bandit` B602 rule (`shell=True`) must never be skipped — all subprocess calls use list form. Report security vulnerabilities privately via [GitHub Security Advisories](https://github.com/rssrn/labro/security/advisories/new).

## License

Apache-2.0 — see [LICENSE](LICENSE).
