# Architecture: Labro — Autonomous Agent Harness

* **Status:** Draft
* **Author:** Ross Arnold
* **Date:** 2026-05-26
* **PRD:** [docs/PRD.md](PRD.md)
* **Roadmap:** [docs/ROADMAP.md](ROADMAP.md)

---

## Table of Contents

1. [Introduction & Goals](#1-introduction--goals)
2. [Constraints](#2-constraints)
3. [System Context](#3-system-context)
4. [Container View](#4-container-view)
5. [Component View](#5-component-view)
6. [Runtime View](#6-runtime-view)
7. [Deployment View](#7-deployment-view)
8. [Cross-Cutting Concepts](#8-cross-cutting-concepts)
9. [Architectural Decisions](#9-architectural-decisions)
10. [Quality Requirements](#10-quality-requirements)
11. [Risks & Technical Debt](#11-risks--technical-debt)

---

## 1. Introduction & Goals

Labro is a self-hosted agent harness that runs AI coding agents on a schedule to perform autonomous maintenance work on software projects — triaging issues, reviewing PRs, investigating alerts, and proposing improvements. See the [PRD](PRD.md) for full product context and requirements.

The harness is deliberately not smart: it selects a task, constructs a scoped prompt, invokes an agent subprocess, records the result, and transitions GitHub labels. All reasoning is delegated to the agent. This separation keeps the harness deterministic, auditable, and independently testable.

This document describes the architecture that satisfies the quality goals below and the constraints in Section 2. Significant design decisions are captured as ADRs in `docs/adr/`.

### Quality Goals

| Priority | Quality Goal | Motivation |
| :--- | :--- | :--- |
| 1 | **Auditability** | Every run must be fully reconstructable from logs — what was selected, why, what the agent did, at what cost. |
| 2 | **Safety / blast-radius control** | Agent actions are bounded by per-project, per-source permission envelopes enforced at invocation time. |
| 3 | **Extensibility** | New projects, task sources, and agents can be added via config only — no code changes required. |
| 4 | **Operational simplicity** | Self-hosted on a single machine; no external dependencies beyond GitHub and optionally Grafana. |
| 5 | **Cost transparency** | Token and time costs are captured per run and queryable. |

### Stakeholders

| Role | Concern |
| :--- | :--- |
| Operator (Ross) | Wants autonomous maintenance with minimal oversight and clear escape hatches. |
| Future operators | Must be able to onboard via config without reading source code. |

---

## 2. Constraints

_Hard constraints the architecture must respect — technical, organisational, or legal._

| Constraint | Rationale |
| :--- | :--- |
| Python 3.12+ | Operator preference; strong ecosystem for CLI tooling and subprocess management. |
| Docker runtime | Sandboxing; reproducible environment; `gh` CLI and agent CLIs pre-installed. |
| No external database service | Operational simplicity; SQLite is the persistence layer — a single bind-mounted file, no server process required. |
| `gh` CLI for GitHub actions | Consistent auth model (`GH_TOKEN`); avoids a separate GitHub SDK dependency. |
| Claude Code CLI as v1 agent | CLI-invocable; harness treats it as a black box invoked via subprocess. Agent abstraction layer supports adding further agents in future versions. |

---

## 3. System Context

_Who and what does Labro interact with? (C4 Level 1)_

```
┌─────────────────────────────────────────────────────────────────┐
│                         Operator                                │
│  (configures projects, reads daily digest, expands permissions) │
└────────────────────────────┬────────────────────────────────────┘
                             │ config + logs + digest
                             ▼
                    ┌────────────────┐
                    │     Labro      │
                    │ (agent harness)│
                    └──┬──────┬───┬──┘
                       │      │   │
          ┌────────────┘      │   └──────────────┐
          ▼                   ▼                  ▼
┌──────────────────┐  ┌───────────────┐  ┌─────────────┐
│   GitHub API     │  │  Grafana API  │  │    Slack    │
│ (issues, PRs,    │  │ (firing       │  │  (incoming  │
│  labels, gh CLI) │  │  alerts)      │  │   webhook)  │
└──────────────────┘  └───────────────┘  └─────────────┘
          │
          ▼
┌──────────────────┐
│  Claude Code CLI │
│  (subprocess)    │
└──────────────────┘
```

**External systems:**

| System | Role |
| :--- | :--- |
| GitHub | Source of tasks (issues, PRs, Dependabot); target of agent actions (comments, PRs, labels). |
| Grafana | Source of firing alert tasks. |
| Claude Code CLI | Agent: invoked for complex reasoning tasks. |
| Slack | Delivery channel for daily digest (incoming webhook). |

---

## 4. Container View

_Top-level deployable units. (C4 Level 2)_

```
┌──────────────────────────────────────────────────────────────┐
│  Docker Container                                            │
│                                                              │
│  ┌──────────────┐   ┌──────────────┐   ┌─────────────────┐  │
│  │   Scheduler  │   │    Harness   │   │   Agent CLIs    │  │
│  │  (system     │──▶│  (Python)    │──▶│  claude         │  │
│  │   cron)      │   │              │   │  (subprocesses) │  │
│  └──────────────┘   └──────┬───────┘   └─────────────────┘  │
│                            │                                 │
│                    ┌───────▼───────┐                         │
│                    │     Store     │                         │
│                    │   (SQLite)    │                         │
│                    └───────────────┘                         │
└──────────────────────────────────────────────────────────────┘
```

| Container | Technology | Responsibility |
| :--- | :--- | :--- |
| Scheduler | System cron (inside container) | Fires harness runs per project on configured cron schedules; fires daily digest. Crontab is generated from `labro.toml` by the Docker entrypoint at container start — operator edits config only. |
| Harness | Python 3.12 | Task selection, prompt construction, agent invocation, label transitions, logging. |
| Agent CLI | Claude Code CLI | Executes the task; interacts with GitHub via `gh`; makes code changes. |
| Store | SQLite (single bind-mounted file) | Persist structured execution records; queried by digest and review CLI. |

---

## 5. Component View

_Internal structure of the Harness. (C4 Level 3)_

```
Harness
├── config/           Config loader & schema validation
├── task_sources/     Pluggable task source modules
│   ├── base.py       Abstract base class / interface
│   ├── grafana_alerts.py
│   ├── gh_label.py
│   └── proactive_improvement.py
├── picker.py         Priority-stack evaluator → selects one task
├── repo.py           Repo preparation: clone or pull to default branch
├── prompt_builder.py Constructs agent prompt from task + permissions + project context
├── agents/           Agent registry and per-agent implementations
│   ├── base.py       Agent ABC, AgentTimeoutError, AgentOutputError
│   ├── _schema.py    Shared OUTCOME_SCHEMA + validate_structured_output
│   ├── _subprocess.py Shared run_cli subprocess helper
│   ├── claude_code.py ClaudeCodeAgent: builds claude -p cmd, parses single-JSON response
│   ├── codex.py      CodexAgent: builds codex exec cmd, parses JSONL stream + output file
│   ├── opencode.py   OpenCodeAgent: builds opencode run cmd, extracts JSON from event stream
│   └── registry.py   id → Agent instance; get_agent(); all_agents()
├── runner.py         Backward-compat re-export shim (logic now in agents/claude_code.py)
├── post_run.py       Label transitions; failure comments
├── store.py          SQLite access layer (execution records, locks, outcome signals)
├── logger.py         Writes execution record to SQLite via store.py
├── digest.py         Daily digest generation and delivery
└── cli.py            Operator CLI entry point (labro subcommands)
```

### CLI subcommands

| Subcommand | Description |
| :--- | :--- |
| `labro run <project>` | Trigger a single run for a project immediately (bypasses scheduler). Accepts `--dry-run` flag: runs task selection and prompt construction but does not acquire a lock, prepare the repo, invoke the agent, write execution records, or apply label transitions. Prints resolved task, agent config, and full prompt text to stdout — useful for inspecting configuration before spending tokens. |
| `labro init` | Bootstrap all configured projects: creates required GitHub labels in each repo if absent. Idempotent — safe to re-run. Labels created: `ai-contributed` (blue `#0075ca`), `ai-failed` (yellow `#e4e669`, description "remove to retry"), `ai-proactive-suggestion` (grey `#cfd3d7`), plus any configured done labels (green `#0e8a16`) and source labels (purple `#7057ff`). `ai-alert:<rule-uid>` labels are created dynamically by `post_run.py` on first alert success, not by `init`; they use blue `#0075ca` with description `"Labro alert tracker: <rule-uid>"`. |
| `labro check` | Pre-flight health check: validates config, checks all required env vars are set, verifies GitHub token has `repo` or `public_repo` scope (via `gh auth status`; may produce false negatives for fine-grained PATs), confirms required labels exist in each configured repo, and — if `claude_assignee` is set — verifies that user is a collaborator on each configured repo (via `gh api repos/{repo}/collaborators/{user}`). Reports pass/fail per check. Safe to run at any time — makes no writes. |
| `labro list-locks` | Show all currently held project locks with `project`, `locked_at`, and age. |
| `labro unlock <project>` | Manually release a stale lock for a project. |
| `labro review` | Print a table of recent execution records from SQLite. Default: last 20 runs. Columns: `started_at`, `project`, `outcome`, `task_source`, `item_url` (truncated), `duration_s`, `total_cost_usd`, `turns_used`, `summary` (truncated). Footer shows total cost and token usage. Flags: `--limit N`, `--project <name>`, `--outcome <success\|failure\|partial\|skipped>`, `--db-path PATH`. Plain text to stdout. |

### Key Interfaces

**TaskSource (base.py)**

```python
class TaskSource:
    def fetch_task(self, project: ProjectConfig) -> Task | None: ...
```

**Agent (agents/base.py)**

```python
class Agent(ABC):
    id: ClassVar[str]                        # registry key, e.g. "claude-code"
    auth_env_vars: ClassVar[tuple[str, ...]] # env vars that satisfy auth
    supports_max_turns: ClassVar[bool] = True

    def invoke(self, prompt: str, config: AgentConfig) -> AgentResult: ...
    def has_auth(self) -> bool: ...          # fast env/file check (used by load_config)
    def validate_auth(self) -> tuple[str, str]: ...  # ("OK  "|"WARN"|"FAIL", msg) for labro check
```

The **agent registry** (`agents/registry.py`) maps CLI id to Agent instance. `get_agent(id)` raises `ValueError` for unknown ids. `load_config` calls `referenced_agents()` to collect all agent ids from the config, then validates auth for each one. See ADR 0006 and `docs/providers/` for per-agent details.

Each agent owns its structured-output delivery method: `ClaudeCodeAgent` uses `--json-schema` (inline string, result in `structured_output` field); `CodexAgent` uses `--output-schema` + `-o` (temp files); `OpenCodeAgent` injects the schema into the prompt and extracts the JSON from the `--format json` event stream. The shared `OUTCOME_SCHEMA` and `validate_structured_output` in `agents/_schema.py` are used by all three.

### Data models

#### `Task`

Produced by `TaskSource.fetch_task()`; consumed by `prompt_builder.py`, `post_run.py`, and `logger.py`. All resolution of label_rule / actor_rule / source / project config overrides happens inside the task source before returning — `Task` carries only the resolved values.

```python
@dataclass
class Task:
    task_id: str                          # UUID v4, generated at selection time
    source: str                           # "grafana-alerts" | "gh-label" | "proactive-improvement"
    description: str                      # human-readable; inserted into prompt section 2
    permitted_actions: list[PermittedAction]  # effective set; inserted into prompt section 3

    # GitHub item reference
    repo: str                  # "owner/repo" — always the project's configured repo
    item_type: str | None      # "issue" | "pr" — None for grafana-alerts and proactive-improvement (no source item exists yet)
    item_number: int | None
    item_url: str | None

    # Label transitions — post_run.py only; None for sources with no pre-existing item
    source_label: str | None       # label to remove on success (gh-label label_rules only; None for actor_rules and other sources)
    done_label: str | None         # label to apply on success (gh-label only; None for other sources)
    grafana_rule_uid: str | None   # rule UID for grafana-alerts tasks; post_run.py applies ai-alert:<rule-uid> to items_created
```

For all tasks, `repo` is always set to the project's configured repo — every task belongs to exactly one project. For `gh-label` tasks, `item_type`, `item_number`, and `item_url` are also populated — the item exists before the agent runs, so `store.py` writes the `items_touched` row at task-selection time. For `grafana-alerts` and `proactive-improvement`, `item_type`, `item_number`, and `item_url` are `None` at selection time; `items_touched` rows are written after the run using `task.repo` + each entry in `items_created` from `AgentResult`.

#### `AgentConfig`

Carries the resolved agent invocation parameters. Produced by the picker alongside `Task`; passed to `Agent.invoke()`. Constructed via `AgentConfig.from_slug(slug, max_turns, timeout_s, permitted_actions)` which parses the slug into its components.

```python
@dataclass
class AgentConfig:
    agent: str           # CLI id, e.g. "claude-code" or "codex"
    slug: str            # full slug for display/logging
    provider: str | None # vendor, e.g. "anthropic"
    model: str | None    # model name only, e.g. "claude-opus-4-7"
    effort: str | None   # e.g. "high"
    max_turns: int  # passed to claude as --max-turns
    timeout_s: int  # subprocess wall-clock timeout
```

#### `AgentResult`

Returned by `Agent.invoke()`; parsed from the Claude Code CLI's JSON response. Consumed by `post_run.py` and `logger.py`.

```python
@dataclass
class AgentResult:
    outcome: str                    # "success" | "failure" | "partial" — from structured_output
    summary: str                    # agent completion reported summary
    actions_taken: list[str]        # human-readable action strings
    items_created: list[ItemRef]    # GitHub items the agent created (for items_touched)
    failure_reason: str | None

    # Top-level response fields (from Claude Code CLI JSON)
    is_error: bool
    num_turns: int
    total_cost_usd: float
    duration_ms: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int

@dataclass
class ItemRef:
    item_type: str    # "issue" | "pr"
    item_number: int
```

`post_run.py` branches on `"success"`, `"partial"`, and `"failure"`. A `"partial"` outcome (agent cut short by turn limit) triggers a handover path distinct from plain failure — see §error_max_turns recovery below.

#### `error_max_turns` recovery

When the Claude CLI exits with `subtype == "error_max_turns"` and no `structured_output`, the runner builds an `AgentResult(outcome="partial")` from salvaged fields (`result`, `total_cost_usd`, token counts) rather than raising `RunnerOutputError`. This preserves budget data and feeds the handover path.

After any non-success outcome, `cli.py` calls `repo.preserve_wip(repo_path, repo, run_id)`, which creates a `labro-wip/<run-id>` branch from any dirty working copy and pushes it to the remote. This is a harness action independent of `permitted_actions` — the user opted into the harness writing WIP branches unconditionally.

### Label State Machine

No in-progress label is used during a run — the project lock (`project_locks` table) is the sole concurrency guard. Labels are only written by `post_run.py` after the agent subprocess exits.

`ai-contributed` is applied to every GitHub item that Labro acts on, regardless of outcome. It is the query surface for ad-hoc GitHub lookups and is never removed by the harness.

#### `gh-label` — label_rules

The trigger label (e.g. `ai-dev`) is the pickup signal. The `ai-failed` and `ai-handover` labels gate re-pickup; the source label is kept so the operator need only remove `ai-failed` to retry. For `ai-handover`, removing the label also re-queues the item.

| Phase | Labels on item | Harness action |
| :--- | :--- | :--- |
| **Eligible** | Has source label (e.g. `ai-dev`) AND NOT `ai-failed` AND NOT `ai-handover` | Picker selects item |
| **Skipped — failed** | Has `ai-failed` | Picker ignores; operator removes `ai-failed` to re-enable |
| **Skipped — handed over** | Has `ai-handover` | Picker ignores; operator removes `ai-handover` to re-queue |
| **Skipped — done** | Has done label (e.g. `ai-dev-done`) | Picker ignores (source label already removed) |
| **Success** | — | Remove source label; apply done label; apply `ai-contributed` |
| **Partial (turn limit)** | — | Apply `ai-handover` + `ai-contributed`; post handover comment (includes WIP branch URL if code was preserved) |
| **Failure** | — | Keep source label; apply `ai-failed`; apply `ai-contributed`; post failure comment (includes WIP branch URL if any) |

#### `gh-label` — actor_rules

No source label to remove — the done label is the "already processed" gate. `ai-failed` and `ai-handover` exclusions apply here too.

| Phase | Labels on item | Harness action |
| :--- | :--- | :--- |
| **Eligible** | Opened by configured actor AND NOT has done label AND NOT `ai-failed` AND NOT `ai-handover` | Picker selects item |
| **Skipped — done** | Has done label | Picker ignores |
| **Skipped — failed** | Has `ai-failed` | Picker ignores |
| **Success** | — | Apply done label; apply `ai-contributed` |
| **Failure** | — | Apply `ai-failed`; apply `ai-contributed`; post failure comment |

#### `grafana-alerts`

No source item exists at run start. The tracking issue is created (or not) by the agent. Dedup is purely on the presence of an open issue carrying `ai-alert:<rule-uid>` — `ai-failed` does not affect dedup.

| Phase | GitHub state | Harness / agent action |
| :--- | :--- | :--- |
| **Eligible** | No open issue with `ai-alert:<rule-uid>` | Source returns task |
| **Skipped — already tracked** | Open issue exists with `ai-alert:<rule-uid>` | Source returns no task; logs `skipped: already tracking #N` |
| **Issue created (success)** | Agent creates tracking issue | `post_run.py` applies `ai-alert:<rule-uid>` (using `task.grafana_rule_uid`) and `ai-contributed` to issue |
| **Failure before issue created** | No tracking issue | No label transition; failure logged; alert retried on every subsequent run (accepted risk — surfaced via digest failure rate). **Dedup gap:** if the agent creates the tracking issue but `structured_output` is malformed, incomplete, or the run aborts between issue creation and response delivery, `post_run.py` never applies `ai-alert:<rule-uid>` — the alert fires again next run and creates a second tracking issue. The dedup check is only as reliable as the label application path. Persistent alerts can silently accumulate duplicate tracking issues; operators should check for duplicate `ai-contributed` issues if an alert fires repeatedly. |
| **Failure after issue created** | Tracking issue exists | `post_run.py` applies `ai-failed` to issue + `ai-contributed`; posts failure comment; future runs still skip (dedup on `ai-alert:<rule-uid>` ignores `ai-failed`) |
| **Alert cleared (issue open)** | Alert no longer firing | `grafana-alerts` source posts "alert cleared" comment; leaves issue open for operator to close |

#### `proactive-improvement`

No source item — the agent creates items from scratch. `ai-proactive-suggestion` is applied by `post_run.py` (not by the agent), so the open-suggestion cap is reliable regardless of agent prompt compliance. The prompt explicitly instructs the agent to open at most one issue or PR per run. `post_run.py` enforces this: only the first entry in `items_created` receives `ai-proactive-suggestion`; any additional entries receive `ai-contributed` only and a warning is logged. This keeps the cap count accurate regardless of agent behaviour.

| Phase | GitHub state | Harness action |
| :--- | :--- | :--- |
| **Eligible** | Open `ai-proactive-suggestion` issues < `max_open_suggestions` | Source returns task |
| **Skipped — cap reached** | Open `ai-proactive-suggestion` issues ≥ cap | Source returns no task |
| **Success — issue created** | Agent creates suggestion issue | `post_run.py` applies `ai-proactive-suggestion` + `ai-contributed` to the issue (from `items_created`) |
| **Success — PR opened** | Agent opens PR | `post_run.py` applies `ai-contributed` to PR; does NOT apply `ai-proactive-suggestion` (PRs are not counted by the cap) |
| **Failure** | No item created | No label transition; failure logged |

#### Label inventory

| Label | Applied by | Purpose | Mutually exclusive with |
| :--- | :--- | :--- | :--- |
| `ai-contributed` | `post_run.py` | Marks every item Labro acted on; query surface | — |
| `ai-failed` | `post_run.py` | Blocks re-pickup; cleared by operator to retry | `ai-<source>-done` (shouldn't coexist — failure precedes done) |
| `ai-alert:<rule-uid>` | `post_run.py` (on success, from `task.grafana_rule_uid`) | Dedup key for `grafana-alerts` | — |
| `ai-proactive-suggestion` | `post_run.py` | Cap counter for open suggestions | — |
| `<done_label>` (e.g. `ai-dev-done`) | `post_run.py` | Marks successful completion; blocks re-pickup | Source label (removed on success) |
| Source labels (e.g. `ai-dev`, `ai-review`) | Operator | Trigger pickup for `gh-label` label_rules | Done label (removed on success) |

---

## 6. Runtime View

_What happens during a single harness run?_

```
Scheduler triggers run(project)   [or: labro run <project> [--dry-run]]
    │
    ▼
Config loaded → project config resolved
    │
    ▼
--dry-run? → task selection + prompt construction → print task / agent config / prompt → exit (no lock, no repo prep, no agent, no SQLite writes)
    │
    ▼
Disabled check: /data/LABRO_DISABLED lockfile present? → log skipped: harness disabled → exit
    │
    ▼
Lock acquired (INSERT into project_locks)
  └── already locked? → log skipped: run in progress → exit
    │
    ▼
daily_budget_usd configured? → query SUM(total_cost_usd) FROM runs WHERE project = :project AND DATE(started_at) = today
  └── spend ≥ budget? → log skipped: daily budget exceeded ($X.XX of $Y.YY used) → release lock → exit
    │
    ▼
Picker iterates priority list
    └── TaskSource.fetch_task()?   None → next source
    │
    ▼
Task selected (or no task → run ends, logged as "skipped")
    │
    ▼
repo.py prepares working copy
  ├── repo absent → git clone; read default branch via `gh repo view`
  └── repo present → checkout default branch + git pull
      └── dirty? → capture `git status --short` output
                 → log warning with file list (surfaced in digest)
                 → git reset --hard + git clean -fd → continue
    │
    ▼
PromptBuilder constructs prompt
  (task description + permitted actions + project context)
    │
    ▼
Agent.invoke(prompt, agent_config)
  → subprocess: claude -p --max-turns N (prompt passed via stdin, not as CLI arg — avoids ARG_MAX limits)
  → stdout/stderr captured
    │
    ▼
post_run.py
  ├── success → remove source label; apply done label; apply ai-contributed
  └── failure → keep source label; apply ai-failed; apply ai-contributed; post failure comment
    │
    ▼
logger.py → write execution record to SQLite (via store.py) → release lock (DELETE from project_locks)
  └── SQLite write failure? → log to stderr; release lock unconditionally (finally block); execution record may be lost
```

---

## 7. Deployment View

_How Labro is deployed and operated._

```
Host machine (single server or dev machine)
└── Docker container
    ├── /app/              Labro source code + entrypoint.sh
    ├── /data/             Single bind-mount from host — all persistent state:
    │   ├── labro.toml     Operator config  (LABRO_CONFIG=/data/labro.toml)
    │   ├── labro.db       SQLite run store
    │   ├── labro.log      Structured run log
    │   ├── repos/         Cloned project repos (LABRO_REPOS_DIR=/data/repos)
    │   └── codex/
    │       └── auth.json  Codex CLI auth — symlinked to ~/.codex/auth.json by entrypoint
    └── env: GITHUB_APP_PRIVATE_KEY_BASE64, CLAUDE_CODE_OAUTH_TOKEN, OPENROUTER_API_KEY, ...
         (injected via --env-file from host; never baked into image)
```

* Container is built from a `Dockerfile` in the repo root.
* `entrypoint.sh` runs at startup: symlinks `codex/auth.json` if present, exports env to `/etc/labro-env`, generates `/etc/cron.d/labro` from `labro.toml`, then execs `crond`. Adding a project requires only a config change and a container restart.
* All persistent state lives under a **single bind-mount** (`-v /your/data/dir:/data`) — easy to back up, inspect, and reason about.
* Secrets are injected via `--env-file` at `docker run` time — never baked into the image or written to config.
* `labro run <project>` invokes a single run on demand without the scheduler — useful during development and debugging.

### `entrypoint.sh` and crontab generation

`entrypoint.sh` runs as PID 1. It performs three steps before handing off to `crond`:

**Step 1 — Export env to a sourcing file.**
`crond` does not inherit the container's environment. `entrypoint.sh` dumps the current environment to `/etc/labro-env` at startup so cron jobs can source it:

```bash
printenv | sed 's/=\(.*\)/="\1"/' > /etc/labro-env
chmod 600 /etc/labro-env
```

Secrets stay out of the crontab file itself; they live only in `/etc/labro-env`, which is root-readable only and not bind-mounted.

**Step 2 — Generate `/etc/cron.d/labro` from `labro.toml`.**

One cron entry per enabled project (runs `labro run <project>`), plus one top-level entry for the digest (runs `labro digest`). The digest covers all projects in a single run, so it gets a single entry regardless of how many projects are configured.

Generated format:

```
# /etc/cron.d/labro — generated by entrypoint.sh at container start. Do not edit.
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin:/usr/local/bin

# Projects
0 * * * *   root  . /etc/labro-env; labro run my-api  >> /var/log/labro/my-api.log  2>&1
0 2 * * *   root  . /etc/labro-env; labro run infra   >> /var/log/labro/infra.log   2>&1

# Digest (covers all projects)
0 8 * * *   root  . /etc/labro-env; labro digest       >> /var/log/labro/digest.log  2>&1
```

Disabled projects (`enabled = false`) are omitted from the crontab. If `[digest] enabled = false`, the digest entry is omitted.

**Step 3 — Exec `crond` in foreground.**

```bash
exec crond -f -l 2
```

`-f` keeps crond in the foreground (required for Docker); `-l 2` sets log level to notice.

**Cron user:** all jobs run as `root` inside the container. The container is personal tooling with no multi-user concerns; running as root avoids permission issues with bind-mounted directories.

**Log rotation:** `/var/log/labro/` accumulates one log file per project plus one for the digest. No log rotation is configured in v1 — log files are not the primary record (SQLite is); they are a secondary debug aid. Add rotation if log files grow problematically.

### Two-repo deployment pattern

Labro separates the **engine** (this repo) from the **operator's config** (a separate private repo). This keeps the labro repo shareable and free of user-specific data, while the config repo holds everything the operator owns:

```
labro repo (public)          config repo (private, operator-owned)
├── src/labro/               ├── labro.toml
├── Dockerfile               ├── .gitignore
├── labro.example.toml       ├── .github/
└── docs/                    │   └── workflows/
    └── config-repo-scaffold/│       ├── labro-deploy.yml   ← auto on labro.toml push
        ├── labro-deploy.yml │       ├── labro-update.yml   ← manual: pull new image
        ├── labro-update.yml │       └── labro-restart.yml  ← manual: refresh secrets
        └── labro-restart.yml└── (GitHub Secrets — see below)
```

**[rssrn/labro-rssrn](https://github.com/rssrn/labro-rssrn)** is a working example of this pattern.

**Secrets** are stored as GitHub repo secrets in the config repo and written to a `.env` file on the host by the deployment workflows — never baked into the image or checked into either repo.

**Config resolution** — the `labro` binary locates `labro.toml` via (highest priority first):
1. `--config <path>` CLI flag
2. `LABRO_CONFIG` environment variable (set to `/data/labro.toml` by the deployment workflows)
3. `./labro.toml` in the current working directory

**GitHub repo secrets** required in the config repo:

| Secret | Notes |
| :--- | :--- |
| `DEPLOY_HOST` | `user@hostname` — server SSH address (Tailscale hostname recommended) |
| `GITHUB_APP_PRIVATE_KEY_BASE64` | `base64 -w 0 your-app.pem` — safe for `--env-file` (no newlines) |
| `CLAUDE_CODE_OAUTH_TOKEN` | If using claude-code agent |
| `OPENROUTER_API_KEY` | If using opencode with OpenRouter |
| `CODEX_API_KEY` | If using codex via OpenAI API billing |
| `CODEX_AUTH_JSON_BASE64` | If using codex CLI subscription billing — `base64 -w 0 ~/.codex/auth.json`; bind-mounted so headless token refresh persists |

**Scaffold workflows** — copy from `docs/config-repo-scaffold/` into your config repo's `.github/workflows/`. The three workflows all: write a fresh `.env` on the host from GitHub secrets, then recreate the container. This means rotating any secret is just: update it in GitHub → run `labro-restart.yml`.

| Workflow | Trigger | What it does |
| :--- | :--- | :--- |
| `labro-deploy.yml` | Push to `labro.toml` | Copies new config + writes `.env` + recreates container (same image) |
| `labro-update.yml` | `workflow_dispatch` | Writes `.env` + pulls `:latest` + recreates container |
| `labro-restart.yml` | `workflow_dispatch` | Writes `.env` + recreates container (same image) |

**Deployment target** — the scaffold assumes SSH access to a self-hosted server running Docker. The scaffold uses [Tailscale](https://tailscale.com) for private networking (no public SSH port needed; the runner advertises `tag:github-runner` and the host allows it via Tailscale SSH ACLs), but any SSH-reachable host works with minor adjustments.

### Config and secret changes on a VPS deployment

The long-running container model requires care when applying updates, because `entrypoint.sh` only runs at container start.

**What requires a restart vs. what does not:**

| Change type | Restart required? | Reason |
| :--- | :--- | :--- |
| Task source config, permitted actions, model, budget | **No** | `labro run` re-reads `labro.toml` on every invocation |
| Cron schedule change, new project added, project disabled | **Yes** | `entrypoint.sh` generates `/etc/cron.d/labro` once at startup |
| Secret rotation (env var change) | **Yes** | `entrypoint.sh` writes `/etc/labro-env` once at startup; running jobs source that file |

**Graceful restart — draining in-flight runs before restarting:**

A plain `docker restart` sends SIGTERM to crond and then SIGKILL after the stop timeout, which may kill an agent mid-task. The safe sequence uses the `LABRO_DISABLED` lockfile and the `project_locks` table to drain first:

```bash
# 1. Prevent new runs from starting (labro run exits immediately if this file exists)
docker exec labro touch /data/LABRO_DISABLED

# 2. Wait for any in-flight run to release its lock (poll every 5 s)
while [ "$(docker exec labro sqlite3 /data/labro.db \
    'SELECT COUNT(*) FROM project_locks')" != "0" ]; do
  echo "waiting for in-flight run to finish…"; sleep 5
done

# 3. Restart — safe, no agent in flight
docker restart labro

# 4. Re-enable (LABRO_DISABLED is in /data/ which is bind-mounted; survives restart)
docker exec labro rm /data/LABRO_DISABLED
```

Steps 1 and 4 can also be performed from the host by touching/removing the file directly under the `/data/` bind-mount path.

> **Note:** `LABRO_DISABLED` lives in `/data/` which is bind-mounted — it survives the restart and must be explicitly removed after the container comes back up. If a workflow or script fails after creating the file, remove it manually: `docker exec labro rm /data/LABRO_DISABLED`.

**Config repo scaffold workflows:**

See [`docs/config-repo-scaffold/`](../config-repo-scaffold/) for ready-to-copy workflow files. The three workflows (`labro-deploy.yml`, `labro-update.yml`, `labro-restart.yml`) share the same structure: write a fresh `.env` on the host from GitHub secrets → gracefully drain in-flight runs → recreate the container. See the Two-repo deployment pattern section above for the full secrets table and workflow summary.

---

## 8. Cross-Cutting Concepts

### Security

* GitHub token scoped to minimum required permissions per project.
* Secrets never written to config or execution records. No output sanitisation pass: secrets (`GH_TOKEN`, `CLAUDE_CODE_OAUTH_TOKEN`/`ANTHROPIC_API_KEY`) are consumed by `gh` and the Claude Code CLI as env vars and have no reason to appear in agent output; the risk of accidental leakage into the structured JSON response is negligible.
* Agent is invoked with its working directory set to the cloned repo under `LABRO_REPOS_DIR/<project-name>` (default `/repos/<project-name>`; `/data/repos/<project-name>` with the single-mount layout), which scopes its default context to the cloned repo. This is a convention, not enforced isolation — Claude Code CLI can navigate to other paths within the container (e.g. `/data/labro.db`). The Docker container boundary is the real filesystem sandbox. See Risks.
* Action Permissions communicated to the agent via the prompt (v1). No runtime enforcement mechanism; the agent is trusted to follow its instructions. A `gh` wrapper for hard enforcement is a v1.1 candidate. See [ADR-003](adr/0003-prompt-only-action-permissions-enforcement.md).

### Observability & Logging

* Every run produces a structured record written to SQLite regardless of outcome.
* Execution record fields: `run_id`, `project`, `task_source`, `task_description`, `agent`, `model`, `started_at`, `ended_at`, `duration_s`, `token_usage`, `turns_used`, `outcome` (`success` | `failure` | `skipped`), `actions_taken`, `failure_reason`.
* Daily digest queries SQLite across all projects: runs fired, tasks per source, skips, token spend, failures.
* Outcome signals (PR merged, issue closed, reactions) are collected by the daily digest job — not the run loop. The digest records its own start time (`digest_start`), then queries `items_touched JOIN runs WHERE runs.ended_at < :digest_start AND items_touched.signals_collected_at IS NULL`. Only runs that completed before the digest fired are eligible — any run still in progress at digest time is skipped and will be picked up on the next digest. This avoids lock-polling and keeps the digest stateless with respect to project run state. The `ai-contributed` label remains the query surface for ad-hoc GitHub lookups. See [ADR-002](adr/0002-github-as-state-store.md).

### Digest spec

`digest.py` runs once per day on a schedule independent of all project crons (configured in `[digest]` in `labro.toml`). It executes four phases in order: collect outcome signals → aggregate run stats → assemble Slack message → POST to `SLACK_WEBHOOK_URL`.

#### Phase 1 — Outcome signal collection

Records `digest_start = now()`. Once a row's `signals_collected_at` is set, it is permanently excluded from future Phase 1 runs — signals are collected once only, not re-collected if the digest later fails in Phase 2–4. This is intentional: signal data is retained in `items_touched` regardless of whether it reached Slack, and the next digest's Phase 2 window will cover the stats. No retry loop is needed in Phase 1.

Queries items eligible for signal collection:

```sql
SELECT it.*, r.project, r.task_source, r.started_at
FROM items_touched it
JOIN runs r ON r.run_id = it.run_id
WHERE r.ended_at < :digest_start
  AND it.signals_collected_at IS NULL
```

For each row: reads current GitHub state via `gh api` (PR state, issue close reason, follow-up commits, 👍/👎 reactions on Labro comments). Writes `outcome_state`, `follow_up_commits`, `thumbs_up`, `thumbs_down`, `signals_collected_at = now()` back to `items_touched`. Failures here are logged and skipped — the row stays uncollected and will be retried next digest.

#### Phase 2 — Run stats aggregation

`window_start` is determined from the last *successful* digest: `SELECT fired_at FROM digests WHERE outcome = 'success' ORDER BY fired_at DESC LIMIT 1`. If no prior successful digest exists, falls back to `digest_start - 24 hours`. This ensures runs from a day where the digest failed are not silently dropped — they appear in the next successful digest's window instead (which may cover more than 24 hours).

```sql
-- Runs per project/source/outcome
SELECT project, task_source, outcome, COUNT(*) AS n
FROM runs
WHERE started_at >= :window_start
GROUP BY project, task_source, outcome;

-- Failure reasons (for failed + skipped rows)
SELECT project, outcome, failure_reason, COUNT(*) AS n
FROM runs
WHERE started_at >= :window_start
  AND outcome IN ('failure', 'skipped')
GROUP BY project, outcome, failure_reason;

-- Cost by project and model
SELECT project, model,
       SUM(total_cost_usd)                              AS cost_usd,
       SUM(input_tokens + output_tokens)                AS total_tokens,
       SUM(cache_read_tokens)                           AS cache_read_tokens
FROM runs
WHERE started_at >= :window_start
GROUP BY project, model;

-- Self-report vs objective outcome delta (all-time; runs where signals have been collected)
-- false_positive: agent said success but GitHub shows closed/rejected
-- false_negative: agent said failure but GitHub shows merged/completed
SELECT r.project,
       COUNT(*) FILTER (
           WHERE r.outcome = 'success'
             AND it.outcome_state IN ('closed_not_planned', 'closed_unmerged')
       )                                               AS false_positives,
       COUNT(*) FILTER (
           WHERE r.outcome = 'failure'
             AND it.outcome_state IN ('merged', 'closed_completed')
       )                                               AS false_negatives,
       COUNT(*) FILTER (WHERE it.signals_collected_at IS NOT NULL) AS signals_with_data
FROM runs r
JOIN items_touched it ON it.run_id = r.run_id
GROUP BY r.project;
```

#### Phase 3 — Slack message structure

Plain Slack mrkdwn (no Block Kit). Four sections separated by `---` dividers.

```
*Labro Digest — {date}*

---
*Runs (last 24h)*
  • {project}: {n} run(s) — {n} success, {n} failure, {n} skipped
    └ skipped: {reason} × {n}
    └ failed: {reason} (run_id: {id})
  ...
  (omit project if 0 runs)

---
*Cost (last 24h)*
  • {project}: ${cost} — {model} ({tokens} tokens, {cache}% cache)
  Total: ${total}
  (omit section if $0 spend)

---
*Outcome signals*
  Collected this digest:
  • {project} #{number} ({type}) — {outcome_state} [link]
  ...
  All-time: {merged} merged · {closed_not_planned} not planned · {closed_completed} completed · {open} open
  PR merge rate: {merged}/{merged+closed_unmerged} · Human override rate: {pct}% had follow-up commits
  Satisfaction: {thumbs_up}👍 {thumbs_down}👎 ({rated} rated) — ratio: {ratio}%
  Self-report accuracy: {false_positives} success→rejected · {false_negatives} failure→accepted ({pct}% disagreement across {n} signals)
  (omit self-report accuracy line if fewer than 3 all-time signals with data)
  (omit "Collected this digest" sub-section if nothing collected)

---
*Awaiting your verdict* (last 7 days, no reaction yet — items older than 7 days without a reaction are not surfaced; outcome signals continue to be collected passively)
  • <{url}|{project} #{number}> — "{summary}" ({task_source}, {date})
  ...
  (omit section if no items)
```

The "Awaiting your verdict" query:

```sql
SELECT it.repo, it.item_type, it.item_number, it.item_url,
       r.project, r.task_source, r.summary, r.started_at
FROM items_touched it
JOIN runs r ON r.run_id = it.run_id
WHERE (it.thumbs_up IS NULL OR it.thumbs_up = 0)
  AND (it.thumbs_down IS NULL OR it.thumbs_down = 0)
  AND r.started_at >= :seven_days_ago
  AND r.outcome = 'success'
ORDER BY r.started_at DESC;
```

Only successful runs are listed — failed runs are surfaced in the Runs section instead.

#### Phase 4 — Delivery

Two steps, in order:

1. **Write to local file** — always writes the assembled message to `/data/digest-YYYY-MM-DD.txt` (UTC date), regardless of what follows. This write happens before the Slack POST so the message is recoverable even if the webhook fails, the URL expires, or Slack rejects the payload.

2. **Slack POST** — single HTTP POST to `SLACK_WEBHOOK_URL`. If the POST fails, the error is logged to stderr and the digest is marked failed in SQLite (a `digests` table: `digest_id`, `fired_at`, `outcome`, `error`). No retry — the next scheduled digest will cover the window. A failed digest does not prevent outcome signals already written in Phase 1 from being retained.

The `digests` table also serves as the scheduling anchor: `labro digest --dry-run` skips Phase 1 (no `signals_collected_at` writes) and Phase 4 (no Slack POST and no file write), assembling and printing the message from already-collected signals only. No `digests` row is written. Zero side effects.

```sql
CREATE TABLE digests (
    digest_id   TEXT    PRIMARY KEY,    -- UUID v4
    fired_at    TEXT    NOT NULL,       -- ISO 8601 UTC
    window_start TEXT   NOT NULL,       -- fired_at - 24h
    outcome     TEXT    NOT NULL CHECK (outcome IN ('success', 'failure')),
    error       TEXT                    -- NULL on success
);
```

### Concurrency Control

* Runs for different projects are fully independent and may execute concurrently — each cron invocation is a separate process with its own working directory under `/repos/`.
* Per-project locks prevent concurrent runs for the *same* project. Locks are held in a SQLite `project_locks` table (`project`, `locked_at`).
* A run begins by attempting to INSERT a lock row; if one already exists, the run exits immediately and logs `skipped: run in progress`.
* Stale locks (process crash, container kill) are detected by age: a lock is treated as stale if its age exceeds `timeout_s + 60` seconds. The 60-second grace period closes the race window where a cron tick fires just as a previous run's subprocess has been killed but its `finally` block has not yet released the lock — without the grace period, the new run would see a lock older than `timeout_s`, overwrite it, and both runs would proceed simultaneously for the same project.
* SQLite is opened in WAL mode to handle concurrent writers across projects safely.
* `labro list-locks` shows all held locks with age; `labro unlock <project>` removes a lock manually.

### Persistence / SQLite Schema

Three tables. All timestamps are ISO 8601 UTC strings. WAL mode is enabled at connection time.

```sql
-- runs: one row per harness run, including skipped runs where no task was selected
CREATE TABLE runs (
    run_id              TEXT    PRIMARY KEY,            -- UUID v4
    project             TEXT    NOT NULL,
    task_source         TEXT,                           -- NULL when outcome = 'skipped' (no task found)
    task_description    TEXT,
    item_url            TEXT,                           -- GitHub URL of the *source* item selected by the picker (gh-label only); NULL for grafana-alerts and proactive-improvement — agent-created items are in items_touched, not here
    trigger_label       TEXT,                           -- the specific label that caused the trigger (label_rules only); NULL for actor_rules, grafana-alerts, proactive-improvement, and skipped runs
    agent               TEXT,                           -- e.g. "claude-code"
    model               TEXT,
    started_at          TEXT    NOT NULL,               -- ISO 8601 UTC
    ended_at            TEXT,
    duration_s          REAL,
    outcome             TEXT    NOT NULL
                            CHECK (outcome IN ('success', 'failure', 'skipped')),
    turns_used          INTEGER,
    total_cost_usd      REAL,
    input_tokens        INTEGER,
    output_tokens       INTEGER,
    cache_read_tokens   INTEGER,
    cache_write_tokens  INTEGER,
    summary             TEXT,                           -- agent completion reported summary
    actions_taken       TEXT,                           -- JSON array of strings
    failure_reason      TEXT    -- for skipped runs: harness-authored structured string (e.g. "skipped: run in progress", "skipped: source error — grafana-alerts") — safe to GROUP BY in digest;
                                -- for failed runs: may include agent-authored prose — display only, not aggregated
);

CREATE INDEX idx_runs_project    ON runs (project);
CREATE INDEX idx_runs_started_at ON runs (started_at);
CREATE INDEX idx_runs_outcome    ON runs (outcome);

-- project_locks: at most one row per project while a run is in progress
CREATE TABLE project_locks (
    project     TEXT    PRIMARY KEY,
    locked_at   TEXT    NOT NULL    -- ISO 8601 UTC; compared against timeout_s for stale-lock detection
);

-- items_touched: GitHub items acted on during a run; one row per item per run.
-- Written by the harness at run time (for gh-label: at task-selection time;
-- for other sources: from items_created in the agent's structured output).
-- Outcome signal columns are NULL until the daily digest job collects them.
CREATE TABLE items_touched (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                  TEXT    NOT NULL    REFERENCES runs (run_id),
    repo                    TEXT    NOT NULL,   -- "owner/repo"
    item_type               TEXT    NOT NULL    CHECK (item_type IN ('issue', 'pr')),
    item_number             INTEGER NOT NULL,
    -- Outcome signals — populated by the digest job, not the run loop
    outcome_state           TEXT    CHECK (outcome_state IN (
                                        'merged',
                                        'closed_completed',
                                        'closed_not_planned',
                                        'closed_unmerged',
                                        'open'
                                    )),
    follow_up_commits       INTEGER,            -- commits on the PR branch after the agent's push, before merge; PRs only
    thumbs_up               INTEGER,            -- count of 👍 reactions on Labro comments
    thumbs_down             INTEGER,            -- count of 👎 reactions on Labro comments
    signals_collected_at    TEXT                -- ISO 8601 UTC; NULL = not yet collected by digest job
);

CREATE INDEX idx_items_touched_run_id    ON items_touched (run_id);
CREATE INDEX idx_items_touched_repo_item ON items_touched (repo, item_type, item_number);

-- digests: one row per digest firing; used by the digest job as a scheduling anchor
CREATE TABLE digests (
    digest_id    TEXT    PRIMARY KEY,   -- UUID v4
    fired_at     TEXT    NOT NULL,      -- ISO 8601 UTC
    window_start TEXT    NOT NULL,      -- fired_at of last successful digest (or fired_at - 24h if no prior success)
    outcome      TEXT    NOT NULL CHECK (outcome IN ('success', 'failure')),
    error        TEXT                   -- NULL on success
);
```

**Schema decisions:**

- Token usage fields (`input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`) are stored as flat columns, not as a JSON blob, so they can be aggregated directly in SQL without JSON extraction.
- `actions_taken` is a JSON array string — used for display only (digest summary, `labro review`), not for outcome matching, so SQL querying is not required.
- `outcome_state` values correspond to: GitHub PR merged (`merged`), PR closed without merge (`closed_unmerged`), issue closed as completed (`closed_completed`), issue closed as not planned (`closed_not_planned`), still open (`open`). `closed_completed` and `closed_not_planned` map to GitHub's `state_reason` field on the issue close event.
- No `ON DELETE CASCADE` — execution records are append-only. `items_touched` rows reference their parent `run_id` for auditability; orphaned rows are not a concern at the current scale.
- Periodic purge of runs older than N days (see Risks) will require a corresponding delete from `items_touched`.

### Dirty-repo recovery

A dirty working copy on run entry means the previous run left uncommitted changes. This happens via two paths:

| Cause | Lock state on next run | How recovery reaches repo.py |
| :--- | :--- | :--- |
| **Agent hit `--max-turns` mid-edit** (most common) | Lock released normally by `finally` block | No stale lock; run proceeds directly to `repo.py` |
| **Container killed / process crash** | Lock is stale (age > `timeout_s`) | Stale lock overwritten first; run then proceeds to `repo.py` |

In both cases `repo.py` detects the dirty state via `git status --porcelain`, captures the file list, logs a warning (included in the execution record and surfaced in the digest), then executes `git reset --hard && git clean -fd` before proceeding. The uncommitted changes are discarded — there is no attempt to salvage them, since the previous run was already recorded as a failure and the agent will re-attempt the work on the current task.

Dirty-repo recovery is a **belt-and-suspenders guard**, not the primary recovery mechanism for either cause. The primary mechanisms are: `--max-turns` terminating the agent cleanly (turn limit) and stale-lock detection (container kill). The dirty-repo check is the final safety net that ensures every run starts from a known-clean state.

### Error Handling

* Agent subprocess timeout → logged as failure; `ai-failed` label applied.
* Task source fetch failure (exception) → logged as warning with reason `skipped: source error — <source_name>`; picker moves to next source. Distinct from `skipped: no task found` so the digest surfaces broken sources as a separate count rather than silently counting them as quiet runs.
* GitHub API errors during agent execution → logged; run aborted cleanly.
* Label transition failure (post-run) → logged as `outcome=failure` with `failure_reason="label transition failed"`; `ai-failed` applied as best-effort fallback. If that also fails, the execution record is written with the failure noted and the item is left in a dirty label state. No retry — the digest surfaces the failure and the operator resolves it manually.
* SQLite write failure (logger) → failure logged to stderr; lock released unconditionally in a `finally` block. Execution record may be lost. A frozen project is a worse outcome than a missing record.

### Configuration

* Single TOML file (`labro.toml`) declares all projects. Parsed with `tomllib` (stdlib); validated with Pydantic at startup. See [ADR-001](adr/0001-toml-config-format.md).
* Invalid config is a hard failure with a clear error message; no runs attempted.
* Required environment variables are validated at startup alongside config. Which vars are required depends on what is configured: `GH_TOKEN` is required unless GitHub App auth is configured, in which case `GITHUB_APP_PRIVATE_KEY` (raw PEM) or `GITHUB_APP_PRIVATE_KEY_BASE64` (base64-encoded PEM, preferred for container deployments) is required instead — labro generates a per-run installation token from it automatically; claude CLI auth requires either `CLAUDE_CODE_OAUTH_TOKEN` (Claude subscription OAuth token — recommended) or `ANTHROPIC_API_KEY` (API key); `OPENROUTER_API_KEY` if using opencode with OpenRouter; `CODEX_API_KEY` or `CODEX_AUTH_JSON_BASE64` if using codex; `GRAFANA_TOKEN` only if any project has a `grafana-alerts` source; `SLACK_WEBHOOK_URL` only if the digest is enabled. Missing required vars are a hard failure with a descriptive error message.
* Required GitHub labels are checked at startup. If any are missing, the harness exits with: "Required label(s) missing in <repo> — run `labro init` to create them." `labro init` creates all required labels idempotently; `labro check` reports label status without writing.
* Config is the only file an operator needs to edit to add a project.
* Emergency pause: create `/data/LABRO_DISABLED` on the host to halt all runs immediately (checked before lock acquisition); remove it to resume. No container restart required.

#### `labro.toml` schema (annotated reference)

```toml
# labro.toml — annotated reference configuration
# All fields are required unless marked (optional).

# ── Global: Claude assignee (optional) ────────────────────────────────────────
# GitHub login assigned to an issue/PR while Claude is working on it.
# Labro assigns this user before invoking the agent and restores the original
# assignee afterwards, regardless of outcome.  Soft-fail: if the user is not a
# collaborator the run continues; `labro check` (M5) verifies this in advance.
# claude_assignee = "claude-code-youruser"   # optional

# ── Global: digest ─────────────────────────────────────────────────────────────
[digest]
enabled = true
cron    = "0 8 * * *"   # 5-field cron; runs inside the container (UTC)
# Delivery target: SLACK_WEBHOOK_URL env var — no secret in config

# ── Global: defaults ───────────────────────────────────────────────────────────
# All fields optional; per-project and per-source blocks override these values.
[defaults]
model     = "claude-code:anthropic/claude-opus-4-7"   # cli:provider/model[@effort]; parsed into agent/provider/model/effort
max_turns = 20                            # --max-turns ceiling for Claude Code CLI
timeout_s = 600                           # subprocess wall-clock timeout in seconds

# ── Project ────────────────────────────────────────────────────────────────────
# Repeat [[projects]] for each managed repo.
[[projects]]
name    = "my-api"          # unique slug; used in execution records, CLI output, lock keys
repo    = "my-org/my-api"   # GitHub "owner/repo"
cron    = "0 * * * *"       # how often the scheduler fires a run for this project
enabled = true              # optional; default true — set false to pause without removing

# Per-project agent overrides (optional — inherit from [defaults] if absent)
model            = "anthropic/claude-sonnet-4-6"
max_turns        = 30
timeout_s        = 900
daily_budget_usd = 5.00   # optional; if today's total spend for this project >= this value,
                           # the run exits after lock acquisition with:
                           # "skipped: daily budget exceeded ($X.XX of $Y.YY used)"
                           # Queried from runs.total_cost_usd WHERE DATE(started_at) = today.
                           # Omit or set to 0.0 to disable.

# Project-level default permitted_actions.
# Inherited by any task source that does not declare its own list.
# Resolution order (most specific wins): per-label/actor rule → source-level → project-level.
# Valid values (PermittedAction enum): "comment_on_issue", "comment_on_pr", "open_pr",
#   "merge_pr", "push_default", "close_issue", "create_issue"
permitted_actions = ["comment_on_issue", "comment_on_pr"]   # conservative project default

# Free-text appended to section 4 (project context) of every prompt (optional).
context = """
This is a Python FastAPI service. All changes must go via a pull request.
Do not modify files under db/migrations/ directly.
"""

# Task sources — evaluated in listed order; first non-None result wins.
# Priority is determined by order; removing an entry disables that source.

# ── grafana-alerts ─────────────────────────────────────────────────────────────
[[projects.task_sources]]
type         = "grafana-alerts"
min_severity = "critical"          # "info" | "warning" | "critical" — lower bound filter; alerts with no severity label are treated as "info"
                                   # when multiple alerts are eligible: highest severity first, then oldest startsAt as tiebreaker
model        = "anthropic/claude-sonnet-4-6" # optional per-source model override
# GRAFANA_TOKEN env var used for API auth

# Source-level list overrides project-level permitted_actions for this source only.
permitted_actions = ["comment_on_issue", "comment_on_pr", "create_issue"]
# create_issue: may open a tracking issue for a firing alert

# ── gh-label ───────────────────────────────────────────────────────────────
[[projects.task_sources]]
type = "gh-label"
# Rule resolution: label_rules and actor_rules are evaluated in config declaration order
# (label_rules first if not interleaved). First matching rule for a given item determines
# its done_label, permitted_actions, and source_label. An item matching multiple rules is
# governed by the first match — later rules are not consulted for that item.
# Selection: all matching items across all rules form a candidate pool; oldest by GitHub
# item created_at is picked. Note: label application time would be more precise for
# label_rules (picks by when the operator requested AI work, not when the issue was filed)
# but requires extra API calls per candidate — deferred to a future version.

# Label-based eligibility: each label entry may declare its own permitted_actions.
# If absent, falls back to source-level then project-level permitted_actions.
[[projects.task_sources.label_rules]]
label             = "ai-dev"        # label that makes an issue/PR eligible for pickup
done_label        = "ai-dev-done"   # applied on success; trigger label removed
permitted_actions = ["comment_on_issue", "comment_on_pr", "open_pr"]

[[projects.task_sources.label_rules]]
label             = "ai-review"
done_label        = "ai-review-done"
permitted_actions = ["comment_on_issue", "comment_on_pr"]

# Actor-based eligibility: matches open PRs/issues from a specific GitHub login.
# No label required on the item — implicit eligibility.
[[projects.task_sources.actor_rules]]
actor             = "dependabot[bot]"   # exact GitHub login match
done_label        = "ai-done"
model             = "anthropic/claude-haiku-4-5"  # route to cheaper model for routine Dependabot PRs
permitted_actions = ["comment_on_pr", "open_pr"]

# ── proactive-improvement ──────────────────────────────────────────────────────
[[projects.task_sources]]
type                 = "proactive-improvement"
selection_strategy   = "agent-chooses"   # "agent-chooses" | "harness-random"
max_open_suggestions = 3                 # source returns no task if open ai-proactive-suggestion issues ≥ this cap
# Built-in targets (full list): "review-app-logs", "review-prometheus-metrics",
# "competitor-analysis", "architecture-review", "security-review",
# "test-coverage-review", "scan-todos", "surprise-me"
targets = ["scan-todos", "test-coverage-review", "security-review"]

permitted_actions = ["comment_on_issue", "open_pr"]

# ── Second project (minimal — inherits [defaults] and no permitted_actions default) ──
[[projects]]
name = "infra"
repo = "my-org/infra"
cron = "0 2 * * *"

[[projects.task_sources]]
type = "gh-label"

[[projects.task_sources.label_rules]]
label             = "ai-todo"
done_label        = "ai-done"
permitted_actions = ["comment_on_issue", "comment_on_pr", "open_pr"]
```

**Schema decisions:**

- `permitted_actions` — string allow-list validated against an enum. `permitted_actions = ["comment_on_issue", "open_pr"]`. Pydantic validates each entry against the `PermittedAction` enum; unknown strings are a hard config error.
- `model` — a CLI-prefixed slug in the form `<cli>[:<provider>/<model>][@<effort>]` (e.g. `claude-code:anthropic/claude-opus-4-7@high`). The CLI id is the agent registry key. The slug format is validated at config load time via `parse_slug()`; the agent implementation uses the parsed `model` and `effort` fields directly. Bare legacy slugs (`anthropic/...`) are rejected at config load time with a helpful message. See `docs/providers/` for per-agent slug examples.
- `timeout_s` — subprocess wall-clock timeout in seconds. The stale-lock age threshold in `store.py` is `timeout_s + 60` (fixed 60-second grace period; not configurable). No separate config key — operators set `timeout_s`; the grace period is an implementation detail of `store.py`.
- `daily_budget_usd` — optional float; omit or set `0.0` to disable. Checked after lock acquisition by querying `SUM(total_cost_usd)` from `runs` for the current UTC date. Skips with a structured reason string so it aggregates cleanly in the digest alongside other skip reasons.
- `gh-label` with no `label_rules` and no `actor_rules` — hard config error at startup. A source that can never match is a misconfiguration, not a valid no-op.

### Documentation

- **`README.md`** (repo root) — operator quickstart: what Labro is, prerequisites, installation, first-run (`labro init` + `labro check`), and a pointer to `docs/` for full reference. This is the entry point for anyone running the project from source; it should be sufficient to get a first run working without reading the architecture doc.
- **`CLAUDE.md` at managed repo roots** — per-project agent instruction contract. Claude Code reads it automatically when invoked in the repo directory; section 4 of every agent prompt explicitly instructs the agent to read it. Operators write this file in each managed repo to encode project conventions, no-go zones, and style rules. It is the primary mechanism for operator-to-agent communication at the per-project level, separate from `labro.toml` which governs harness behaviour.
- **`docs/adr/NNN-title.md`** — architectural decisions that need more context than a table row. Write an ADR when a non-obvious decision is made that affects the system's structure, constraints, or quality properties. `NNN` is a zero-padded sequence number; Section 9 maintains the index. ADRs are append-only — update status to `Superseded` rather than editing the original.
- **`docs/ARCHITECTURE.md`, `docs/PRD.md`, `docs/ROADMAP.md`** — design and planning docs maintained alongside the code. No auto-generated API docs are planned: Labro is a CLI tool with no library surface, and the annotated `labro.toml` reference in §8 Configuration serves as the operator API reference.

### Testing & Static Analysis

Quality gates are enforced via pre-commit hooks (`.pre-commit-config.yaml`). Fast, file-scoped checks run pre-commit; slow or project-wide checks run pre-push.

#### Toolchain

| Tool | Stage | Purpose |
| :--- | :--- | :--- |
| **ruff** (lint + format) | pre-commit | Style, imports, fast bug patterns; auto-fixes applied |
| **mypy** (strict) | pre-commit | Full type checking; strict mode enforced from day one — clean-slate start makes this tractable, and Labro's dataclass-heavy model benefits from it |
| **bandit** | pre-commit | SAST; skips `B404`/`B603`/`B607` (subprocess by name, list-arg form — the safe pattern); `B602` (`shell=True`) is **not** skipped and is a hard error |
| **shellcheck** | pre-commit | Lints `entrypoint.sh`; sub-second; catches quoting, unset-variable, and pipeline errors in the crontab-generation script |
| **check-toml** | pre-commit | Validates `labro.toml` syntax before config parsing is attempted |
| **pytest** (+ pytest-cov) | pre-commit | Unit tests; coverage floor starts at 70% in M1, raised 5 pp per milestone as new components land |
| **pip-audit** | pre-push | OSV-based dependency vulnerability scan; once-per-day marker avoids redundant scans on repeated pushes |

**`shell=False` rule:** all subprocess calls must use list-form args with `shell=False` (the Python default). This is a hard architectural rule — not a lint suggestion — because task descriptions and label names may contain operator-controlled text that would be injectable if passed through a shell. Enforced by bandit `B602` (not skipped) and code review.

#### Test boundaries

| Layer | Test approach | Mocking strategy |
| :--- | :--- | :--- |
| `config/` — schema validation | Unit | None — pure Pydantic; test valid and invalid TOML inputs including unknown `permitted_actions` values |
| `picker.py` — priority list | Unit | `TaskSource.fetch_task` stubbed to return `Task \| None` per scenario |
| `prompt_builder.py` — four-section prompt | Unit | None — pure function; assert all four sections present, correct ordering, permitted actions enumerated |
| `task_sources/gh_label.py` | Unit | `gh` CLI calls mocked via `subprocess` fixture; fixture responses are real `gh api` JSON payloads captured once |
| `task_sources/grafana_alerts.py` | Unit | HTTP client mocked; fixture responses from real Grafana API captures |
| `task_sources/proactive_improvement.py` | Unit | `gh` CLI mocked; cap-check and target-selection paths exercised |
| `post_run.py` — label state machine | Unit | `gh` CLI calls mocked; assert exact label add/remove sequence per state machine path |
| `store.py` / `logger.py` | Unit | SQLite in-memory (`:memory:`); no mocking needed — real schema exercised |
| `digest.py` — stats aggregation + message assembly | Unit | SQLite in-memory; HTTP POST mocked; assert message structure and `digests` table state |
| `runner.py` / `agents/claude_code.py` | Integration | Subprocess invoked against `claude --help` or a no-op fixture; JSON response shape validated — must assert on top-level fields (`is_error`, `num_turns`, `total_cost_usd`) **and** on `structured_output` shape specifically (required fields present, `outcome` within enum, `items_created` is an array of `{item_type, number}`) |
| Live GitHub + live agent | Explicit out of scope | `labro run --dry-run` is the manual integration test; no automated test hits real GitHub or spends tokens |

#### Coverage policy

Coverage is measured over all non-integration modules. The floor starts at 70% in M1 and increases by 5 percentage points per milestone as new components are added. `runner.py` and `agents/` are excluded from the coverage floor — those paths are exercised by integration tests only.

---

## 9. Architectural Decisions

_Record significant decisions here, or link to individual ADR files in `docs/adr/`._

| ID | Decision | Status | Date |
| :--- | :--- | :--- | :--- |
| [ADR-001](adr/0001-toml-config-format.md) | Use TOML for configuration file format (`labro.toml`) | Accepted | 2026-05-26 |
| [ADR-002](adr/0002-github-as-state-store.md) | Use GitHub labels as the state store for outcome tracking; universal `ai-contributed` marker label | Accepted | 2026-05-26 |
| [ADR-003](adr/0003-prompt-only-action-permissions-enforcement.md) | Prompt-only enforcement for action permissions in v1; no `gh` wrapper script | Accepted | 2026-05-26 |
| [ADR-004](adr/0004-sqlite-persistence.md) | Use SQLite as the persistence layer; no external database service | Accepted | 2026-05-26 |

> _Use `docs/adr/NNN-title.md` for decisions that need more context than a table row._

---

## 10. Quality Requirements

_Testability and quality gates for the architecture._

| Scenario | Stimulus | Expected Response |
| :--- | :--- | :--- |
| Task source returns no task | All sources exhausted | Run logged as `skipped`; no agent invoked; no labels changed. |
| Agent exceeds max turns | Turn limit hit | Run terminated; logged as `failure`; `ai-failed` applied. |
| GitHub API returns 403 | Label transition call | Error logged; run marked failed; no retry in same run. |
| Config file is invalid TOML | Startup | Hard exit with descriptive error; no runs attempted. |
| Required env var missing | Startup | Hard exit with descriptive error naming the missing var; no runs attempted. |
| Required GitHub label missing | Startup | Hard exit: "Required label(s) missing in <repo> — run `labro init`"; no runs attempted. |
| New project added to config | Config change only | Project picked up on next scheduler cycle; no code change required. |
| Unknown `permitted_actions` value in config | Config load | Pydantic validation error; hard exit naming the invalid value and valid alternatives. |
| `picker.py` receives all-`None` task sources | All sources return `None` | Returns `(None, None)`; no `AgentConfig` constructed; run logged as `skipped`. |
| `prompt_builder.py` called with a task | Any `Task` input | Output contains exactly four sections in order; permitted actions section enumerates only the effective `permitted_actions`; no section is empty. |
| `post_run.py` label_rule success path | Agent returns `outcome="success"` | Source label removed; done label applied; `ai-contributed` applied; no `ai-failed`; no failure comment. |
| `post_run.py` label_rule failure path | Agent returns `outcome="failure"` | Source label kept; `ai-failed` applied; `ai-contributed` applied; failure comment posted. |
| `post_run.py` actor_rule success path | Agent returns `outcome="success"` | Done label applied; `ai-contributed` applied; no source label to remove; no `ai-failed`. |
| `daily_budget_usd` reached | Today's spend ≥ configured cap | Run logged as `skipped: daily budget exceeded ($X.XX of $Y.YY used)`; no agent invoked; lock released. |
| `store.py` lock acquisition | Project not currently locked | `INSERT` succeeds; `project_locks` row present with correct `project` and `locked_at`. |
| `store.py` lock contention | Project already locked (non-stale) | `INSERT` fails; returns `False`; no second lock row created. |
| `store.py` stale lock | Lock age > `timeout_s` | Existing row overwritten; new lock acquired; run proceeds. |
| `gh` call uses `shell=False` | Any subprocess invocation | All `subprocess` calls use list-form args; no `shell=True` anywhere in codebase (enforced by bandit B602). |
| `runner.py` receives malformed `structured_output` | CLI response missing required fields or invalid `outcome` enum value | `runner.py` fails loudly with a descriptive error (logged as `failure`); execution record written with `failure_reason`; does not silently produce a garbage record or treat as success. |
| `store.py` stale-lock detection | Lock age is between `timeout_s` and `timeout_s + 60` (within grace period) | Lock is treated as **not** stale; new run exits with `skipped: run in progress`; only one run proceeds. |

---

## 11. Risks & Technical Debt

| Risk | Likelihood | Impact | Mitigation |
| :--- | :--- | :--- | :--- |
| Agent takes actions outside permission envelope | Low–Medium | High | Prompt-only enforcement (v1); audit logs enable detection; `gh` wrapper as hard stop in v1.1 if needed. Risk accepted based on observed Claude Code instruction-following. |
| Agent accesses files outside the project repo | Low | Low–Medium | Working directory scoping is convention only; Docker is the real boundary. Agent could read `/data/labro.db` or other repos under `/repos/`. Accepted in v1 — single-operator personal tooling. Consider read-only bind mounts for `/config/` and `/data/` in v1.1 if this becomes a concern. |
| Agent completion reporting is unreliable | High | Medium | Accept for v1; track as metric; consider downstream outcome checks in v1.1. |
| SQLite file grows unboundedly | Low | Low | Add a periodic purge of execution records older than N days before sustained operation. |
| `gh` CLI auth token expires | Medium | High | Monitor token expiry; surface in daily digest. |
| Runaway agent session costs | Medium | Medium | `--max-turns` for Claude Code CLI; configurable timeout for all agents. |
| GitHub API rate limits exhausted | Low–Medium | Medium | Authenticated limit is 5 000 req/hour. At 10 projects × hourly runs × ~8 calls/run = 1 920 calls/day — well under the ceiling for normal operation. Risk increases if `grafana-alerts` checks for an open tracking issue every run during a persistent alert storm, or if `items_touched` rows accumulate with pagination across many AI-labelled issues. Mitigation: surface remaining rate-limit headroom in the daily digest (one `gh api rate_limit` call at digest time); add pagination awareness in `grafana_alerts.py` before sustained multi-project operation. |
| `claude` CLI update silently changes response shape | Medium | High | `structured_output` format is a single point of failure for the result pipeline. Mitigation: pin the `claude` CLI version in the Dockerfile; `runner.py` must schema-validate `structured_output` before use and fail loudly if the shape is unexpected. See Design Notes. |
| `grafana-alerts` dedup gap creates duplicate tracking issues | Low–Medium | Low–Medium | If the agent creates a tracking issue but `structured_output` is malformed or the run aborts before delivery, `post_run.py` never applies `ai-alert:<rule-uid>` — the alert fires again next run and creates a second issue. Accepted risk for v1; digest failure rate surfaces repeated failures. Operators should check for duplicate `ai-contributed` issues if a persistent alert recurs unexpectedly. |
| `agent-chooses` runs have higher cost than `harness-random` | Medium | Low–Medium | The `agent-chooses` strategy passes the full target list and lets the agent pick scope; broad targets (e.g. `architecture-review`, `competitor-analysis`) routinely consume more turns and tokens than narrowly-scoped `harness-random` or `gh-label` runs. The global `max_turns` and `timeout_s` apply equally to all strategies — there is no per-strategy cap. Mitigation: `daily_budget_usd` limits exposure per project per day; digest cost reporting surfaces unexpectedly expensive proactive runs. Per-strategy turn/cost overrides are a v1.1 candidate if the global cap proves too coarse. |

---

## Design Notes

### Prompt structure (`prompt_builder.py`)

Each prompt passed to the agent has four sections, in order:

1. **Role + harness context** — a short paragraph explaining that the agent is operating autonomously on behalf of Labro, on a schedule, with no human present. It should act decisively within its permitted actions or explicitly report that it cannot complete the task — it must not ask clarifying questions or wait for input.

2. **Task** — the task description from the task source. For `gh-label`: GitHub issue/PR title, body, and URL. For `grafana-alerts`: alert name, rule UID, severity, and current labels. For `proactive-improvement`: depends on `selection_strategy` — `harness-random` passes a single pre-selected target; `agent-chooses` passes the full target list with an explicit instruction to pick exactly one and open at most one issue or PR.

3. **Permitted actions** — an explicit enumeration of the *GitHub write operations* the agent may and may not perform in this run (derived from the effective action permissions). Scoped narrowly to side-effectful GitHub actions only — read operations, web searches, MCP tool calls (e.g. context7, web fetch), and local file operations are always unrestricted. Example: "You may: post a comment on a GitHub issue or PR, open a pull request. You must not: merge a pull request, approve a pull request, push directly to the default branch."

4. **Project context** — repo name, default branch, and an instruction to read `CLAUDE.md` at the repo root for project-specific conventions and constraints. Claude Code reads `CLAUDE.md` automatically when invoked in the repo directory; the prompt reinforces this as an explicit instruction. Any additional project-level context declared in `labro.toml` is appended here.

### `claude -p` structured output for agent result parsing

`claude -p` supports `--output-format json` combined with `--json-schema`, which causes the model to populate a `structured_output` field in the JSON response according to the provided schema. The top-level response also includes `total_cost_usd`, `num_turns`, `duration_ms`, `is_error`, and `usage` (token breakdown) — all directly usable for logging without parsing prose. **Verified against Claude Code CLI as of 2026-05-26.**

Example invocation (prompt passed via stdin to avoid ARG_MAX limits):

```bash
echo "<prompt>" | claude -p \
  --output-format json \
  --json-schema '{
    "type": "object",
    "properties": {
      "outcome":        { "type": "string", "enum": ["success", "failure", "partial"] },
      "summary":        { "type": "string" },
      "actions_taken":  { "type": "array", "items": { "type": "string" } },
      "items_created":  {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "item_type": { "type": "string", "enum": ["issue", "pr"] },
            "number":    { "type": "integer" }
          },
          "required": ["item_type", "number"]
        }
      },
      "failure_reason": { "type": "string" }
    },
    "required": ["outcome", "summary", "actions_taken", "items_created"]
  }'
```

Example top-level response shape (abridged — verified output):

```json
{
  "type": "result",
  "subtype": "success",
  "is_error": false,
  "num_turns": 2,
  "total_cost_usd": 0.01439205,
  "duration_ms": 5250,
  "result": "<prose response text>",
  "usage": {
    "input_tokens": 3,
    "output_tokens": 108,
    "cache_read_input_tokens": 41156,
    "cache_creation_input_tokens": 111
  },
  "modelUsage": {
    "claude-sonnet-4-6": {
      "inputTokens": 3,
      "outputTokens": 108,
      "cacheReadInputTokens": 41156,
      "cacheCreationInputTokens": 111,
      "costUSD": 0.01439205
    }
  },
  "structured_output": {
    "outcome": "success",
    "summary": "Opened a PR fixing the null pointer in the auth handler.",
    "actions_taken": ["git commit -m 'fix null pointer in auth handler'", "gh pr create"],
    "items_created": [{"item_type": "pr", "number": 43}],
    "failure_reason": null
  }
}
```

**Implication for the harness:** `runner.py` can parse the JSON response directly — no prose scraping needed. `logger.py` reads `total_cost_usd`, `num_turns`, `duration_ms`, `usage`, and `structured_output` verbatim into the SQLite execution record. Failure detection uses `is_error == true` OR `subtype != "success"`. The `modelUsage` object is ignored — the flat token/cost columns in `runs` are sufficient for v1, where each run uses exactly one model.

**Version pinning and schema validation requirements:** The entire result pipeline depends on `claude -p --output-format json --json-schema` producing the shape above. Three safeguards are required:

1. **Pin the `claude` CLI version in the Dockerfile.** An unpinned `claude` upgrade could silently change the response shape and break every run. Pin to a specific released version; update deliberately.
2. **Schema-validate `structured_output` in `runner.py` before use.** After JSON-parsing the CLI response, `runner.py` must validate that `structured_output` contains the expected fields (`outcome`, `summary`, `actions_taken`, `items_created`) and that `outcome` is one of the declared enum values. A missing or malformed `structured_output` must fail loudly with a clear error — not silently produce a garbage execution record or swallow the run as a success.
3. **Integration test must cover `structured_output` specifically.** The `runner.py` integration test (see §8 Testing) must assert on the shape of `structured_output` in the parsed response, not just top-level fields.

The `items_created` field is the structured hook for outcome tracking: after the run, the harness writes one row to the `items_touched` table per entry in `items_created`. For `gh-label` tasks, the harness writes to `items_touched` at task-selection time (before the agent runs) since the item is already known. The daily digest job then queries `items_touched` and reads current GitHub state to populate outcome signals.

`actions_taken` remains a human-readable string array — used for the digest summary and the execution record, not for outcome matching.
