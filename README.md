# Labro — Autonomous Agent Harness

![Labro](docs/labro_logo.png)

[![License: GPL v3](https://img.shields.io/badge/license-GPLv3-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue?logo=python&logoColor=white)](pyproject.toml)
[![Docker](https://img.shields.io/github/v/release/rssrn/labro?label=ghcr.io&logo=docker&logoColor=white)](https://github.com/rssrn/labro/pkgs/container/labro)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![mypy: strict](https://img.shields.io/badge/mypy-strict-blue)](https://mypy-lang.org/)
[![bandit](https://img.shields.io/badge/security-bandit-yellow)](https://github.com/PyCQA/bandit)
[![Claude Code](https://img.shields.io/badge/agent-Claude_Code-8A2BE2?logo=anthropic&logoColor=white)](https://claude.ai/code)
[![GitHub](https://img.shields.io/badge/platform-GitHub-181717?logo=github&logoColor=white)](https://github.com)

AI coding agents like Claude Code deliver real productivity gains — but they still demand attention. You have to decide what to work on next, queue the task, watch the run, and review the output. That supervisory overhead is the bottleneck, not the agent.

Labro is designed to reduce it. It runs Claude Code on a schedule, picks the next task according to your configured priorities, and records the result — without you having to be present. Maintenance work that would otherwise pile up happens in the background: issues get triaged, PRs get reviewed, and alerts get investigated while you focus on something else.

**A natural fit for Claude subscribers with headless credits to use.** From June 2026 Anthropic allocates a [monthly pool of Agent SDK credits](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan) to Pro, Max, Team, and Enterprise plan holders for headless/programmatic use — separate from interactive chat usage. Unused credits don't roll over at the end of each billing cycle. Labro gives you a concrete, low-risk way to put them to work on your own repos rather than letting them expire.

**Going on holiday? Heads-down on a deadline?** Leave the backlog to Labro before you disconnect — issues get triaged, PRs get reviewed, and alerts get investigated while you're away. Your subscription keeps earning its keep, even when you're not at the keyboard.

Named after cleaner wrasse fish stations on coral reefs (_Labroides dimidiatus_), which provide a designated, high-value, symbiotic service to reef inhabitants, Labro acts as an always-available autonomous worker that keeps your projects healthy with minimal human supervision.

The operator configures which projects to monitor, what tasks to prioritise, which agent and model to use per task type, and what actions the agent is permitted to take. The harness is deterministic and auditable — it selects a task, constructs a prompt, invokes the agent, records the result, and gets out of the way.

**Human-in-the-loop by default, autonomous when you're ready.** Out of the box Labro is conservative: the agent opens PRs and posts comments, but merges and deployments are left for a human to approve. The autonomy dial is yours to turn — widen the `permitted_actions` list and adjust the system prompt in `labro.toml`, and Labro can merge approved PRs, push to a staging environment, or deploy to production on a schedule. The configuration is the only gatekeeper; there is no separate mode to enable.

- **Scheduled, unattended runs** — cron-driven via GitHub Actions or a VPS; no one needs to be at the keyboard
- **Priority-based task picking** — configurable label rules and actor rules determine what gets worked on first
- **Flexible deployment** — run as a long-lived VPS container with crond, or as a one-shot container per scheduled GitHub Actions job; both patterns are documented with ready-to-use config
- **Per-project daily spend cap** — set `daily_budget_usd` to hard-stop spending once the limit is reached; the skipped run is recorded so accounting stays accurate
- **Turn-limit handover** — when the agent exhausts its turn budget mid-task, Labro commits any in-progress edits to a `labro-wip/<run-id>` branch, posts a handover comment on the issue with the WIP branch link, and parks the item under `ai-handover` until a human re-queues it — no code is lost and no credits are silently wasted on a retry
- **Graceful failure labelling** — success, partial, and failure outcomes each get distinct GitHub labels so the state of every item is visible at a glance without reading run logs
- **Full audit trail** — every run writes outcome, cost, token usage, and actions to a local SQLite database
- **Emergency pause** — drop a `LABRO_DISABLED` flag file to stop new runs instantly without restarting containers; any run already in progress finishes normally
- **Multi-provider support** _(planned)_ — spread scheduled work across free-tier quotas from multiple AI providers (Claude, Gemini, and others); top priority on the near-term roadmap

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
  -v "$PWD/labro.toml:/app/labro.toml:ro" \
  labro:latest run my-project --dry-run
```

### 4. Pre-flight check and label setup

Run `labro check` to validate your config, environment variables, GitHub token connectivity, and that all required labels exist:

```bash
docker run --rm \
  -e GH_TOKEN=<your-github-token> \
  -e CLAUDE_CODE_OAUTH_TOKEN=<your-token> \
  -v "$PWD/labro.toml:/app/labro.toml:ro" \
  labro:latest check
```

Each line of output is prefixed with `OK  `, `WARN`, or `FAIL`. Fix any `FAIL` items before proceeding. `WARN` items (such as the OAuth token check) are informational — Labro will still run.

If labels are missing, create them with `labro init`:

```bash
docker run --rm \
  -e GH_TOKEN=<your-github-token> \
  -v "$PWD/labro.toml:/app/labro.toml:ro" \
  labro:latest init
```

This creates every label referenced in `labro.toml` across all configured repos using `gh label create --force` (idempotent — safe to re-run).

### 5. Validate the `claude` CLI (before live runs)

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
8. **Invoke agent** — run `claude -p` as a subprocess with the prompt on stdin; validate the `structured_output` payload. If the agent hits its turn limit (`--max-turns`), the harness recovers gracefully — see [Turn limits and partial runs](#turn-limits-and-partial-runs) below
9. **Preserve WIP** — on any non-success outcome, if the working copy is dirty the harness commits it to a `labro-wip/<run-id>` branch and pushes it, so no in-progress code edits are silently discarded
10. **Post-run labels** — apply label transitions and post a comment to the GitHub item (see [Label transitions](#label-transitions))
11. **Write run record** — INSERT a row into `runs` with outcome, cost, token usage, and action list
12. **Release lock** — DELETE from `project_locks` (always; in a `finally` block)

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

### Turn limits and partial runs

Labro is designed for budget-conscious use. Low `max_turns` values keep costs predictable, but they mean the agent will sometimes hit its limit mid-task — especially on larger issues. This is expected and handled as a first-class outcome rather than a hard error.

When the agent exhausts its turn budget:

1. **Cost is recorded** — `total_cost_usd` and token counts are salvaged from the CLI response and written to the `runs` table as normal, so daily-budget accounting stays accurate even for incomplete runs.
2. **Code is preserved** — if the agent made any file edits before being cut off, the harness commits them to a `labro-wip/<run-id>` branch and pushes it to the remote. The branch URL appears in the handover comment.
3. **Handover comment posted** — Labro comments on the issue/PR with the agent's last message, a link to the WIP branch (if any), and the instruction to remove `ai-handover` to re-queue.
4. **Item is parked** — the `ai-handover` label is applied. The picker will not re-attempt the item until a human reviews the comment and removes the label — intentional friction to avoid burning the turn budget again without a config change.

> **Tuning tip:** if an item is repeatedly hitting the turn limit, either raise `max_turns` for that project/rule in `labro.toml`, or break the issue into smaller scoped tasks before re-queuing.

The prompt also asks the agent to post an early progress comment on the item and update it in place as work proceeds (`gh issue comment --edit-last`). This way analysis work is visible on the ticket even if the session ends before the agent can fill in `structured_output`.

### Label transitions

After each live run, Labro updates the GitHub labels on the acted-on item automatically. The exact transitions depend on the task source rule type and the run outcome.

#### `label_rule` path (label-triggered tasks)

| Outcome | Labels added | Labels removed |
|---|---|---|
| success | `<done_label>` (e.g. `ai-dev-done`), `ai-contributed` | `<source_label>` (e.g. `ai-dev`) |
| partial (turn limit) | `ai-handover`, `ai-contributed` | _(none — source label kept)_ |
| failure | `ai-failed`, `ai-contributed` | _(none — source label kept)_ |

#### `actor_rule` path (polling-based tasks, no source label)

| Outcome | Labels added | Labels removed |
|---|---|---|
| success | `<done_label>`, `ai-contributed` | _(none)_ |
| partial (turn limit) | `ai-handover`, `ai-contributed` | _(none)_ |
| failure | `ai-failed`, `ai-contributed` | _(none)_ |

#### Re-queueing items

**After a partial run (`ai-handover`):** review the handover comment (and WIP branch if present), then remove `ai-handover` to re-queue:

```bash
gh issue edit <number> --remove-label "ai-handover" --repo <owner/repo>
```

**After a failure (`ai-failed`):** remove `ai-failed` to re-queue (`ai-contributed` can stay — it's informational and never blocks re-pickup):

```bash
gh issue edit <number> --remove-label "ai-failed" --repo <owner/repo>
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

### `labro review` (recommended)

`labro review` prints a formatted table of recent runs directly from the SQLite database:

```bash
docker exec labro labro review --limit 10
docker exec labro labro review --project my-project --outcome failure
```

Flags:

| Flag | Default | Description |
|---|---|---|
| `--limit N` | 20 | Maximum runs to show |
| `--project NAME` | _(all)_ | Filter to one project |
| `--outcome` | _(all)_ | One of `success`, `failure`, `partial`, `skipped` |
| `--db-path PATH` | `/data/labro.db` | Override DB path |

The footer shows total runs, total cost, and total token usage across the displayed rows.

### Raw SQLite (advanced)

The database is at `/data/labro.db` inside the container, bind-mounted to wherever you point `--volume` on the host.

**Everything for one run:**

```bash
sqlite3 -column -header /data/labro.db "
  SELECT * FROM runs          WHERE run_id = '<run_id>';
  SELECT * FROM items_touched WHERE run_id = '<run_id>';
"
```

**Items touched in a specific run:**

```bash
sqlite3 -column -header /data/labro.db \
  "SELECT * FROM items_touched WHERE run_id = '<run_id>';"
```

> **Tip:** `-column -header` formats output as aligned columns with a header row. Add `-json` instead for JSON output, or `-csv` for CSV.

---

## Operator CLI Reference

All subcommands read `--config` (default: `$LABRO_CONFIG` or `./labro.toml`) from the global flag.

### `labro init [--project NAME]`

Creates all GitHub labels referenced in `labro.toml` across every enabled project. Uses `gh label create --force` — idempotent, safe to re-run. Exits 1 if any label creation fails (but continues to attempt the rest).

```bash
labro init                        # all enabled projects
labro init --project my-project   # one project only
```

Run this once when onboarding a new project, or after adding new label rules to `labro.toml`.

### `labro check [--project NAME]`

Pre-flight health check — validates config, environment variables, GitHub connectivity, label presence, and (optionally) collaborator access. Read-only, no side effects.

```bash
labro check
labro check --project my-project
```

Each line is prefixed with `OK  `, `WARN`, or `FAIL`. Exits 1 if any `FAIL` is present.

- **`ANTHROPIC_API_KEY`** — validated by calling `GET /v1/models` (no tokens spent)
- **`CLAUDE_CODE_OAUTH_TOKEN`** — presence only; value cannot be validated without a live API call
- **`gh auth status`** — confirms the GitHub token is authenticated
- **Labels** — checks that every label referenced in config exists on each repo
- **`claude_assignee`** — if set in config, verifies the user is a collaborator on each repo

### `labro review [--limit N] [--project NAME] [--outcome OUTCOME] [--db-path PATH]`

Prints a formatted table of recent runs from SQLite. See [Inspecting run records](#inspecting-run-records) for full flag details.

### `labro list-locks [--db-path PATH]`

Shows currently held project locks with their age. Locks older than `timeout_s + 60` seconds are marked `[STALE]`.

```bash
labro list-locks
```

If a lock appears stale (the run that acquired it has clearly finished or crashed), use `labro unlock` to release it.

### `labro unlock <project> [--db-path PATH]`

Manually releases a stale project lock so the next scheduled run can proceed.

```bash
labro unlock my-project
```

This is a last-resort recovery tool. Under normal operation locks are released automatically in a `finally` block at the end of every run. A lock only gets stuck if the container was killed mid-run before the `finally` block executed.

---

## Docker Deployment

### Deployment modes

Labro supports two production deployment modes:

**GitHub Actions (recommended)** — run Labro as a scheduled workflow in your config repo. No VPS required. Each workflow invocation is a one-shot container run; the agent handles one task and exits. Use this pattern for low-frequency schedules (daily/hourly) or when you already have GitHub Actions available.

**VPS with crond (always-on)** — run Labro as a long-lived container on a server. The container generates a crontab at startup from `labro.toml` and runs `crond` as PID 1. Use this for sub-hourly schedules or when you want a persistent process.

> **Entrypoint behaviour:** the two modes are driven by whether you pass a command to `docker run`.
> - **No command** (VPS crond mode): `docker run labro:latest` — `entrypoint.sh` runs `labro gen-crontab`, writes `/etc/cron.d/labro`, and execs `crond -f` as PID 1.
> - **With a command** (one-shot / GitHub Actions): `docker run labro:latest labro run my-project` — the entrypoint skips cron entirely and execs the given command directly.
>
> No cron job is installed until the no-command path runs; the one-shot path never touches cron at all.
>
> **Local testing — persistent container, no cron:** pass `sleep infinity` as the command to keep the container alive without installing a crontab, then invoke runs manually with `docker exec`:
> ```bash
> docker run -d --name labro-test \
>   -e GH_TOKEN=<token> \
>   -e CLAUDE_CODE_OAUTH_TOKEN=<token> \
>   -v "$PWD/labro.toml:/app/labro.toml:ro" \
>   labro:latest sleep infinity
>
> docker exec labro-test labro run my-project --dry-run
> ```

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
