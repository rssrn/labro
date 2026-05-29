# Labro — Autonomous Agent Harness

![Labro](docs/labro_logo.png)

[![License: GPL v3](https://img.shields.io/badge/license-GPLv3-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue?logo=python&logoColor=white)](pyproject.toml)
[![Docker](https://ghcr-badge.egpl.dev/rssrn/labro/latest_tag?trim=major&label=ghcr.io)](https://github.com/rssrn/labro/pkgs/container/labro)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![mypy: strict](https://img.shields.io/badge/mypy-strict-blue)](https://mypy-lang.org/)
[![bandit](https://img.shields.io/badge/security-bandit-yellow)](https://github.com/PyCQA/bandit)
[![Claude Code](https://img.shields.io/badge/agent-Claude_Code-8A2BE2?logo=anthropic&logoColor=white)](https://claude.ai/code)
[![GitHub](https://img.shields.io/badge/platform-GitHub-181717?logo=github&logoColor=white)](https://github.com)

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
- A **GitHub token** for the repos you want to monitor (`GH_TOKEN`) — see [GitHub token setup](#github-token-setup) below
- A **claude CLI auth credential** — needed for live agent runs (M2+), not for `--dry-run`. Two options:
  - **`CLAUDE_CODE_OAUTH_TOKEN`** (recommended) — OAuth token tied to your Claude subscription (Pro/Max). Generate once with `claude setup-token` on your dev machine.
  - **`ANTHROPIC_API_KEY`** (untested) — standard Anthropic API key; bills your API account. If both vars are set, this takes precedence over the OAuth token.

### GitHub token setup

`GH_TOKEN` must belong to an account that has **collaborator access** (or ownership) of every repo in your `labro.toml`. The token needs the following permissions on those repos:

| Permission | Level | Why |
|---|---|---|
| Contents | Read & write | Push branches for PRs |
| Issues | Read & write | Comment on issues, add/remove labels |
| Metadata | Read-only | List issues, repo lookup (required by GitHub) |
| Pull requests | Read & write | Open PRs |

**Fine-grained PAT (recommended):** create the token under the account that owns the repos (e.g. your personal account), not under a bot account. Fine-grained PATs issued for account A cannot access private repos owned by account B even when account A is a collaborator — GitHub only grants fine-grained PAT access to repos owned by the token's issuing account. Select "Only select repositories" and add each repo explicitly.

**Classic PAT:** use `repo` scope. Simpler, but broader than necessary.

> **Bot accounts:** if you run Labro as a dedicated bot user (e.g. `my-bot`), create the token on your main account (the repo owner), not on the bot account. The token controls what the `gh` CLI can read/write; the `claude_assignee` field in `labro.toml` controls which GitHub user the agent acts as on issues and PRs.

### 1. Clone and build

```bash
git clone https://github.com/rssrn/labro.git
cd labro
docker build --target base -t labro:latest .
```

> **Build targets:** the Dockerfile has two stages. `--target base` (production) omits the
> test suite and dev extras. The default target (`dev`, built without `--target`) includes
> `tests/` and dev extras — useful for contributors and CI, but slightly larger. The
> `labro:latest` tag is conventionally the production image.

**ARM64 / Oracle Cloud Ampere A1:** the image is arch-aware. Build natively on the instance, or cross-build from an amd64 host with:

```bash
docker buildx build --target base --platform linux/arm64 -t labro:arm64 .
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

## Live Run Loop

When you run `labro run <project>` without `--dry-run`, the harness executes the following steps in order:

1. **Load config** — parse and validate `labro.toml` (or `$LABRO_CONFIG`)
2. **Check `LABRO_DISABLED`** — if `/data/LABRO_DISABLED` exists, print `skipped: harness disabled` and exit immediately; no lock is acquired and no SQLite record is written
3. **Acquire run lock** — INSERT into `project_locks`; if a non-stale lock already exists, print `skipped: run in progress` and exit
4. **Budget check** — if `daily_budget_usd` is configured, query today's spend from `runs`; if the limit is reached, write a skipped record to SQLite and exit
5. **Pick task** — run the picker over all configured task sources; if nothing is found, write a skipped record and exit
6. **Prepare repo** — clone or pull the target repo into `/repos/<slug>`; if the working copy is dirty (agent was interrupted mid-edit), log a warning then `git reset --hard && git clean -fd`
7. **Build prompt** — construct the four-section prompt from the resolved task and project context
8. **Invoke agent** — run `claude -p` as a subprocess with the prompt on stdin; validate the `structured_output` payload
9. **Write run record** — INSERT a row into `runs` with outcome, cost, token usage, and action list
10. **Release lock** — DELETE from `project_locks` (always; in a `finally` block)

### Required environment variables

| Variable | Required | Notes |
|---|---|---|
| `GH_TOKEN` | Yes | GitHub token with Issues/PRs/Contents read & write on monitored repos — see [GitHub token setup](#github-token-setup) |
| `CLAUDE_CODE_OAUTH_TOKEN` | Recommended | OAuth token from `claude setup-token` on your dev machine; tied to your Pro/Max subscription |
| `ANTHROPIC_API_KEY` | Alternative | Standard Anthropic API key; bills your API account. If **both** are set, this takes precedence |

### Emergency pause — `LABRO_DISABLED`

To stop Labro from picking up new tasks without restarting containers:

```bash
# Pause — create the flag file in the /data volume:
touch /data/LABRO_DISABLED

# Resume — remove it:
rm /data/LABRO_DISABLED
```

The check happens before lock acquisition. Any run already in progress finishes normally; only new runs are blocked.

### Label transitions

After each live run, Labro updates the GitHub labels on the acted-on item automatically. The exact transitions depend on the task source rule type and whether the agent succeeded or failed.

#### `label_rule` path (label-triggered tasks)

| Outcome | Labels added | Labels removed |
|---|---|---|
| success | `<done_label>` (e.g. `ai-dev-done`), `ai-contributed` | `<source_label>` (e.g. `ai-dev`) |
| failure | `ai-failed`, `ai-contributed` | _(none — source label kept)_ |

#### `actor_rule` path (polling-based tasks, no source label)

| Outcome | Labels added | Labels removed |
|---|---|---|
| success | `<done_label>`, `ai-contributed` | _(none)_ |
| failure | `ai-failed`, `ai-contributed` | _(none)_ |

#### Retrying a failed item

When an item carries `ai-failed`, the picker will not pick it up again. To re-queue it, remove both `ai-failed` and `ai-contributed`:

```bash
gh issue edit <number> --remove-label "ai-failed,ai-contributed" --repo <owner/repo>
```

If the task was label-triggered, also ensure the source label (e.g. `ai-dev`) is still present.

#### `items_touched` table

Labro writes a row to the `items_touched` SQLite table **before** the agent runs, as soon as the task is selected. This means the row exists even if the agent times out or crashes — it records which item was attempted, not whether the attempt succeeded.

```sql
SELECT repo, item_type, item_number FROM items_touched;
```

---

### Daily budget cap — `daily_budget_usd`

Add to your project stanza in `labro.toml` to cap per-project spending per calendar day (UTC):

```toml
[[projects]]
name             = "my-project"
repo             = "my-org/my-repo"
daily_budget_usd = 2.00    # skip if today's spend already >= $2.00
```

Omit the field (or set it to `0`) to disable the cap. When the budget is exceeded, Labro writes a `skipped` record to SQLite with the reason `skipped: daily budget exceeded ($X.XX of $Y.YY used)` and exits without invoking the agent.

---

## Inspecting run records

The SQLite database is at `/data/labro.db` inside the container, bind-mounted to wherever you point `--volume` on the host (e.g. `/tmp/labro-data/labro.db` in the quickstart examples).

**Everything for one run (host, from a local smoke-test mount):**

```bash
sqlite3 -column -header /tmp/labro-data/labro.db "
  SELECT * FROM runs        WHERE run_id = 'a1cf583f-e1e1-4464-993c-b71efa1e279f';
  SELECT * FROM items_touched WHERE run_id = 'a1cf583f-e1e1-4464-993c-b71efa1e279f';
"
```

**Recent runs across all projects:**

```bash
sqlite3 -column -header /data/labro.db \
  "SELECT run_id, project, outcome, started_at, failure_reason FROM runs ORDER BY started_at DESC LIMIT 20;"
```

**Items touched in a specific run:**

```bash
sqlite3 -column -header /data/labro.db \
  "SELECT * FROM items_touched WHERE run_id = '<run_id>';"
```

> **Tip:** `-column -header` formats output as aligned columns with a header row. Add `-json` instead for JSON output, or `-csv` for CSV.

---

## Docker Deployment

### Deployment modes

Labro supports two production deployment modes:

**GitHub Actions (recommended)** — run Labro as a scheduled workflow in your config repo. No VPS required. Each workflow invocation is a one-shot container run; the agent handles one task and exits. Use this pattern for low-frequency schedules (daily/hourly) or when you already have GitHub Actions available.

**VPS with crond (always-on)** — run Labro as a long-lived container on a server. The container generates a crontab at startup from `labro.toml` and runs `crond` as PID 1. Use this for sub-hourly schedules or when you want a persistent process.

### GHCR image

Pre-built images are published to GHCR on every version tag:

```
ghcr.io/rssrn/labro:<tag>
```

Always pin to a specific tag — `:latest` is not published (pin discipline prevents silent response-shape drift):

```bash
docker pull ghcr.io/rssrn/labro:v0.4.0
```

### Bind-mount layout

| Host path | Container path | Purpose |
|---|---|---|
| `./labro.toml` | `/app/labro.toml` | Config (read-only) |
| `/opt/labro/data/` | `/data/` | SQLite DB, lock files, `LABRO_DISABLED` flag |
| `/opt/labro/repos/` | `/repos/` | Cloned repos (cache) |

The `/data/` volume must be persistent across container restarts. `/repos/` can be ephemeral but caching it avoids repeated full clones.

Use `LABRO_CONFIG` to point at a non-default config path inside the container:

```bash
docker run -e LABRO_CONFIG=/config/labro.toml ...
```

### GitHub Actions one-shot (recommended)

Add this workflow to your config repo's `.github/workflows/`:

```yaml
# .github/workflows/labro-run.yml
on:
  schedule:
    - cron: '0 9 * * *'   # match the cron in your labro.toml
  workflow_dispatch:

jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run labro
        run: |
          docker run --rm \
            -e GH_TOKEN=${{ secrets.GH_TOKEN }} \
            -e CLAUDE_CODE_OAUTH_TOKEN=${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }} \
            -v $PWD/labro.toml:/app/labro.toml:ro \
            ghcr.io/rssrn/labro:v0.4.0 labro run my-project
```

### VPS crond mode

Start the container once; it generates `/etc/cron.d/labro` from `labro.toml` and execs `crond -f`:

```bash
docker run -d --name labro \
  --restart unless-stopped \
  -e GH_TOKEN=<token> \
  -e CLAUDE_CODE_OAUTH_TOKEN=<token> \
  -v /opt/labro/config/labro.toml:/app/labro.toml:ro \
  -v /opt/labro/data:/data \
  -v /opt/labro/repos:/repos \
  ghcr.io/rssrn/labro:v0.4.0
```

Verify the crontab was generated correctly:

```bash
docker exec labro cat /etc/cron.d/labro
```

### Graceful restart procedure

When updating the config or rotating secrets, drain in-flight runs before restarting:

```bash
# 1. Signal no new runs
docker exec labro touch /data/LABRO_DISABLED

# 2. Wait for any run in progress to finish
while [ "$(docker exec labro sqlite3 /data/labro.db 'SELECT COUNT(*) FROM project_locks')" != "0" ]; do
  echo "waiting…"; sleep 5
done

# 3. Restart (entrypoint regenerates crontab on start)
docker restart labro

# 4. Re-enable
docker exec labro rm -f /data/LABRO_DISABLED
```

### Config repo scaffold

For VPS deployments, Labro ships two ready-to-use workflow files you can copy into your config repo's `.github/workflows/`:

```bash
cp docs/config-repo-scaffold/labro-deploy.yml  <config-repo>/.github/workflows/
cp docs/config-repo-scaffold/labro-restart.yml <config-repo>/.github/workflows/
```

Add `VPS_HOST`, `VPS_USER`, and `VPS_SSH_KEY` as GitHub Secrets in the config repo.

- **`labro-deploy.yml`** — fires automatically when `labro.toml` is pushed to the config repo; copies the updated config to the VPS and performs a graceful restart.
- **`labro-restart.yml`** — manual trigger only (`Actions → Run workflow`); performs a graceful restart without copying files. Use after rotating a secret.

---

## Project Initiation

The following documents define the product and architecture:

- **[Product Requirements Document](docs/PRD.md)** — problem statement, design principles, functional requirements, and success metrics.
- **[Architecture](docs/ARCHITECTURE.md)** — system context, component design, runtime flow, and architectural decisions.
- **[Roadmap](docs/ROADMAP.md)** — delivery milestones and per-file completion tracking.
- **[Domain Glossary](CONTEXT.md)** — canonical definitions for terms used across all Labro documents and code.

### [Architectural Decision Records](docs/adr/)
