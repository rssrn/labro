# Labro — Autonomous Agent Harness

![Labro](docs/labro_logo.png)

Labro is a self-hosted harness that runs AI coding agents on a schedule to do useful, unsupervised maintenance work on software projects — triaging issues, reviewing PRs, investigating alerts, and proposing improvements.

Named after cleaner wrasse fish stations on coral reefs (_Labroides dimidiatus_), which provide a designated, high-value, symbiotic service to reef inhabitants, Labro acts as an always-available autonomous worker that keeps projects healthy with minimal human supervision.

The operator configures which projects to monitor, what tasks to prioritise, which agent and model to use per task type, and what actions the agent is permitted to take. The harness is deterministic and auditable — it selects a task, constructs a prompt, invokes the agent, records the result, and gets out of the way.

---

There are two ways to run Labro: **Docker** (recommended for production and first-time use) and **local Python** (recommended for development and contributing).

---

## Quickstart — Docker

The `Dockerfile` bundles everything Labro needs: Python 3.12, the `gh` CLI, and a pinned `claude` CLI. This is the recommended way to run Labro in production.

### Prerequisites

- **[Docker](https://docs.docker.com/get-docker/)** (or a compatible runtime such as Podman)
- A **GitHub token** with read access to the repos you want to monitor (`GH_TOKEN`)
- A **claude CLI auth credential** — needed for live agent runs (M2+), not for `--dry-run`. Two options:
  - **`CLAUDE_CODE_OAUTH_TOKEN`** (recommended) — OAuth token tied to your Claude subscription (Pro/Max). Generate once with `claude setup-token` on your dev machine.
  - **`ANTHROPIC_API_KEY`** (untested) — standard Anthropic API key; bills your API account. If both vars are set, this takes precedence over the OAuth token.

### 1. Clone and build

```bash
git clone https://github.com/rssrn/labro.git
cd labro
docker build -t labro:latest .
```

**ARM64 / Oracle Cloud Ampere A1:** the image is arch-aware. Build natively on the instance, or cross-build from an amd64 host with:

```bash
docker buildx build --platform linux/arm64 -t labro:arm64 .
```

### 2. Write a minimal `labro.toml`

```toml
[digest]
enabled = false

[defaults]
model = "claude-sonnet-4-6"

[[projects]]
name       = "my-project"
repo       = "my-org/my-repo"
cron       = "0 * * * *"

[[projects.task_sources]]
type = "gh-delegated"

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
  -v "$PWD/labro.toml:/app/labro.toml:ro" \
  labro:latest run my-project --dry-run
```

### 4. Validate the `claude` CLI (before live runs)

Before running Labro with a live agent (M2+), confirm `claude -p` works inside the container. Use whichever auth route applies to you:

**Option A — Claude subscription OAuth token (Pro/Max; recommended):**

Generate the token once on your dev machine with `claude setup-token`, then:

```bash
docker run --rm \
  --entrypoint sh \
  -e CLAUDE_CODE_OAUTH_TOKEN=<your-token> \
  labro:latest \
  -c 'echo "hello" | claude -p --output-format json'
```

**Option B — Anthropic API key (untested):**

```bash
docker run --rm \
  --entrypoint sh \
  -e ANTHROPIC_API_KEY=<your-key> \
  labro:latest \
  -c 'echo "hello" | claude -p --output-format json'
```

> **Note:** if both `CLAUDE_CODE_OAUTH_TOKEN` and `ANTHROPIC_API_KEY` are set, `ANTHROPIC_API_KEY` takes precedence and bills your API account.

The response should contain top-level `type`, `is_error`, and `result` fields. If it fails with an auth error requiring interactive login, resolve the container auth strategy before proceeding to M2 — this is the day-one blocker for live agent runs.

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

## Project Initiation

The following documents define the product and architecture:

- **[Product Requirements Document](docs/PRD.md)** — problem statement, design principles, functional requirements, and success metrics.
- **[Architecture](docs/ARCHITECTURE.md)** — system context, component design, runtime flow, and architectural decisions.
- **[Roadmap](docs/ROADMAP.md)** — delivery milestones and per-file completion tracking.
- **[Domain Glossary](CONTEXT.md)** — canonical definitions for terms used across all Labro documents and code.

### [Architectural Decision Records](docs/adr/)
