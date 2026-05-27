# Labro — Autonomous Agent Harness

![Labro](docs/labro_logo.png)

Labro is a self-hosted harness that runs AI coding agents on a schedule to do useful, unsupervised maintenance work on software projects — triaging issues, reviewing PRs, investigating alerts, and proposing improvements.

Named after cleaner wrasse fish stations on coral reefs (_Labroides dimidiatus_), which provide a designated, high-value, symbiotic service to reef inhabitants, Labro acts as an always-available autonomous worker that keeps projects healthy with minimal human supervision.

The operator configures which projects to monitor, what tasks to prioritise, which agent and model to use per task type, and what actions the agent is permitted to take. The harness is deterministic and auditable — it selects a task, constructs a prompt, invokes the agent, records the result, and gets out of the way.

---

## Quickstart (development)

### Prerequisites

- **Python 3.12+**
- **[uv](https://docs.astral.sh/uv/)** — fast Python package manager (`pip install uv` or see uv docs)
- **[gh](https://cli.github.com/)** — GitHub CLI, authenticated (`gh auth login`)
- **[pre-commit](https://pre-commit.com/)** — installed via the dev dependencies below

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

> ⚠️ **M1 status:** `labro run --dry-run` is not yet implemented. The command will be available once [M1](docs/ROADMAP.md) is complete. The steps below are the intended first-run flow.

Create a minimal `labro.toml` pointing at a GitHub repo where you have an open issue labelled `ai-dev`:

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

Then run:

```bash
export GH_TOKEN=<your-github-token>
labro run my-project --dry-run
```

Labro will print the resolved task, agent config, and full four-section prompt to stdout — no tokens spent, no writes, no side effects.

---

## Project Initiation

Labro is currently in the design phase. The following documents define the product and architecture:

- **[Product Requirements Document](docs/PRD.md)** — problem statement, design principles, functional requirements, and success metrics.
- **[Architecture](docs/ARCHITECTURE.md)** — system context, component design, runtime flow, and architectural decisions.
- **[Roadmap](docs/ROADMAP.md)** — delivery milestones and per-file completion tracking.
- **[Domain Glossary](CONTEXT.md)** — canonical definitions for terms used across all Labro documents and code.

### [Architectural Decision Records](docs/adr/)
