# Architecture: Labro — Autonomous Agent Harness

* **Status:** Draft
* **Author:** Ross Arnold
* **Date:** 2026-05-26
* **PRD:** [docs/PRD.md](PRD.md)

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
| Store | SQLite (single bind-mounted file) | Persist structured run records; queried by digest and review CLI. |

---

## 5. Component View

_Internal structure of the Harness. (C4 Level 3)_

```
Harness
├── config/           Config loader & schema validation
├── task_sources/     Pluggable task source modules
│   ├── base.py       Abstract base class / interface
│   ├── grafana_alerts.py
│   ├── gh_delegated.py
│   └── proactive_improvement.py
├── picker.py         Priority-stack evaluator → selects one task
├── repo.py           Repo preparation: clone or pull to default branch
├── prompt_builder.py Constructs agent prompt from task + permissions + project context
├── agents/           Agent abstraction layer
│   ├── base.py       Abstract agent interface
│   └── claude_code.py
├── runner.py         Invokes agent subprocess; captures output
├── post_run.py       Label transitions; failure comments
├── store.py          SQLite access layer (run records, locks, outcome signals)
├── logger.py         Writes run record to SQLite via store.py
├── digest.py         Daily digest generation and delivery
└── cli.py            Operator CLI entry point (labro subcommands)
```

### CLI subcommands

| Subcommand | Description |
| :--- | :--- |
| `labro run <project>` | Trigger a single run for a project immediately (bypasses scheduler). |
| `labro init` | Bootstrap all configured projects: creates required GitHub labels in each repo if absent. Idempotent — safe to re-run. Labels created: `ai-contributed`, `ai-failed`, `ai-proactive-suggestion`, plus any configured done/source labels. `ai-alert:<rule-uid>` labels are created dynamically on first alert fire, not by `init`. |
| `labro check` | Pre-flight health check: validates config, checks all required env vars are set, verifies GitHub token scopes, and confirms required labels exist in each configured repo. Reports pass/fail per check. Safe to run at any time — makes no writes. |
| `labro list-locks` | Show all currently held project locks with `project`, `locked_at`, and age. |
| `labro unlock <project>` | Manually release a stale lock for a project. |
| `labro review` | Print a table of recent run records from SQLite. Default: last 20 runs. Columns: `started_at`, `project`, `task_source`, `outcome`, `turns_used`, `total_cost_usd`, `task_description` (truncated). Failures include `failure_reason`. Flags: `--limit N`, `--project <name>`, `--outcome <success\|failure\|skipped>`. Plain text to stdout. |

### Key Interfaces

**TaskSource (base.py)**

```python
class TaskSource:
    def fetch_task(self, project: ProjectConfig) -> Task | None: ...
```

**Agent (agents/base.py)**

```python
class Agent:
    def invoke(self, prompt: str, config: AgentConfig) -> AgentResult: ...
```

---

## 6. Runtime View

_What happens during a single harness run?_

```
Scheduler triggers run(project)
    │
    ▼
Config loaded → project config resolved
    │
    ▼
Lock acquired (INSERT into project_locks)
  └── already locked? → log skipped: run in progress → exit
    │
    ▼
Picker iterates priority stack
    └── TaskSource.fetch_task()?   None → next source
    │
    ▼
Task selected (or no task → run ends, logged as "skipped")
    │
    ▼
repo.py prepares working copy
  ├── repo absent → git clone; read default branch via `gh repo view`
  └── repo present → checkout default branch + git pull
      └── dirty? → log warning (surfaced in digest) + git reset --hard + git clean -fd
    │
    ▼
PromptBuilder constructs prompt
  (task description + permitted actions + project context)
    │
    ▼
Agent.invoke(prompt, agent_config)
  → subprocess: claude -p "..." --max-turns N
  → stdout/stderr captured
    │
    ▼
post_run.py
  ├── success → apply done label, remove source label, apply ai-contributed
  └── failure → apply ai-failed, post failure comment, apply ai-contributed
    │
    ▼
logger.py → write run record to SQLite (via store.py) → release lock (DELETE from project_locks)
  └── SQLite write failure? → log to stderr; release lock unconditionally (finally block); run record may be lost
```

---

## 7. Deployment View

_How Labro is deployed and operated._

```
Host machine (single server or dev machine)
└── Docker container
    ├── /app/              Labro source code
    │   └── entrypoint.sh  Generates crontab from labro.toml; starts crond
    ├── /config/           labro.toml (bind-mounted from host)
    ├── /data/             labro.db — SQLite store (bind-mounted from host)
    ├── /repos/            Cloned project repos (bind-mounted from host)
    └── env: GH_TOKEN, ANTHROPIC_API_KEY, GRAFANA_TOKEN, SLACK_WEBHOOK_URL, ...
```

* Container is built from a `Dockerfile` in the repo root.
* `entrypoint.sh` reads `labro.toml` at container start, writes `/etc/cron.d/labro`, then starts `crond`. Adding a project requires only a config change and a container restart.
* Config, data, and repos live on the host via bind mounts (survives container restarts).
* Secrets are injected as environment variables (not baked into the image).
* `labro run <project>` invokes a single run on demand without the scheduler — useful during development and debugging.

---

## 8. Cross-Cutting Concepts

### Security

* GitHub token scoped to minimum required permissions per project.
* Secrets never written to logs; agent output sanitised before persistence.
* Agent runs with file system access scoped to the cloned repo directory only.
* Permitted Action Set communicated to the agent via the prompt (v1). No runtime enforcement mechanism; the agent is trusted to follow its instructions. A `gh` wrapper for hard enforcement is a v1.1 candidate. See [ADR-003](adr/0003-prompt-only-permitted-action-enforcement.md).

### Observability & Logging

* Every run produces a structured record written to SQLite regardless of outcome.
* Run record fields: `run_id`, `project`, `task_source`, `task_description`, `agent`, `model`, `started_at`, `ended_at`, `duration_s`, `token_usage`, `turns_used`, `outcome` (`success` | `failure` | `skipped`), `actions_taken`, `failure_reason`.
* Daily digest queries SQLite across all projects: runs fired, tasks per source, skips, token spend, failures.
* Outcome signals (PR merged, issue closed, reactions) are collected by the daily digest job — not the run loop. The digest queries the `items_touched` SQLite table, reads current GitHub state, and writes signals back against the originating `run_id`. The `ai-contributed` label remains the query surface for ad-hoc GitHub lookups. See [ADR-002](adr/0002-github-as-state-store.md).

### Concurrency Control

* Runs for different projects are fully independent and may execute concurrently — each cron invocation is a separate process with its own working directory under `/repos/`.
* Per-project locks prevent concurrent runs for the *same* project. Locks are held in a SQLite `project_locks` table (`project`, `locked_at`).
* A run begins by attempting to INSERT a lock row; if one already exists, the run exits immediately and logs `skipped: run in progress`.
* Stale locks (process crash, container kill) are detected by age: any lock older than the configured run timeout is treated as stale and overwritten on the next attempt.
* SQLite is opened in WAL mode to handle concurrent writers across projects safely.
* `labro list-locks` shows all held locks with age; `labro unlock <project>` removes a lock manually.

### Error Handling

* Agent subprocess timeout → logged as failure; `ai-failed` label applied.
* Task source fetch failure → logged as warning; picker moves to next source.
* GitHub API errors during agent execution → logged; run aborted cleanly.
* Label transition failure (post-run) → logged as `outcome=failure` with `failure_reason="label transition failed"`; `ai-failed` applied as best-effort fallback. If that also fails, the run record is written with the failure noted and the item is left in a dirty label state. No retry — the digest surfaces the failure and the operator resolves it manually.
* SQLite write failure (logger) → failure logged to stderr; lock released unconditionally in a `finally` block. Run record may be lost. A frozen project is a worse outcome than a missing record.

### Configuration

* Single TOML file (`labro.toml`) declares all projects. Parsed with `tomllib` (stdlib); validated with Pydantic at startup. See [ADR-001](adr/0001-toml-config-format.md).
* Invalid config is a hard failure with a clear error message; no runs attempted.
* Required environment variables are validated at startup alongside config. Which vars are required depends on what is configured: `GH_TOKEN` and `ANTHROPIC_API_KEY` are always required; `GRAFANA_TOKEN` only if any project has a `grafana-alerts` source; `SLACK_WEBHOOK_URL` only if the digest is enabled. Missing required vars are a hard failure with a descriptive error message.
* Required GitHub labels are checked at startup. If any are missing, the harness exits with: "Required label(s) missing in <repo> — run `labro init` to create them." `labro init` creates all required labels idempotently; `labro check` reports label status without writing.
* Config is the only file an operator needs to edit to add a project.

#### `labro.toml` schema (annotated reference)

```toml
# labro.toml — annotated reference configuration
# All fields are required unless marked (optional).

# ── Global: digest ─────────────────────────────────────────────────────────────
[digest]
enabled = true
cron    = "0 8 * * *"   # 5-field cron; runs inside the container (UTC)
# Delivery target: SLACK_WEBHOOK_URL env var — no secret in config

# ── Global: defaults ───────────────────────────────────────────────────────────
# All fields optional; per-project and per-source blocks override these values.
[defaults]
model     = "claude-opus-4-7"   # passed to claude via --model
max_turns = 20                  # --max-turns ceiling for Claude Code CLI
timeout_s = 600                 # subprocess wall-clock timeout in seconds

# ── Project ────────────────────────────────────────────────────────────────────
# Repeat [[projects]] for each managed repo.
[[projects]]
name    = "my-api"          # unique slug; used in run records, CLI output, lock keys
repo    = "my-org/my-api"   # GitHub "owner/repo"
cron    = "0 * * * *"       # how often the scheduler fires a run for this project
enabled = true              # optional; default true — set false to pause without removing

# Per-project agent overrides (optional — inherit from [defaults] if absent)
model     = "claude-sonnet-4-6"
max_turns = 30
timeout_s = 900

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
min_severity = "critical"          # "info" | "warning" | "critical" — lower bound filter
model        = "claude-sonnet-4-6" # optional per-source model override
# GRAFANA_TOKEN env var used for API auth

# Source-level list overrides project-level permitted_actions for this source only.
permitted_actions = ["comment_on_issue", "comment_on_pr", "create_issue"]
# create_issue: may open a tracking issue for a firing alert

# ── gh-delegated ───────────────────────────────────────────────────────────────
[[projects.task_sources]]
type = "gh-delegated"
# Selection: when multiple items match across all rules, oldest by created_at is picked.
# label_rules and actor_rules are evaluated together as a single candidate pool.

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
model             = "claude-haiku-4-5"  # route to cheaper model for routine Dependabot PRs
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
type = "gh-delegated"

[[projects.task_sources.label_rules]]
label             = "ai-todo"
done_label        = "ai-done"
permitted_actions = ["comment_on_issue", "comment_on_pr", "open_pr"]
```

**Schema decisions:**

- `permitted_actions` — string allow-list validated against an enum. `permitted_actions = ["comment_on_issue", "open_pr"]`. Pydantic validates each entry against the `PermittedAction` enum; unknown strings are a hard config error.
- `model` — passed through opaquely to the CLI; not validated at config load time. Avoids needing schema updates when new model names are released; the CLI surfaces an error if the value is unrecognised.
- `timeout_s` — single value used both as the subprocess wall-clock timeout and as the stale-lock age threshold. No separate key.
- `gh-delegated` with no `label_rules` and no `actor_rules` — hard config error at startup. A source that can never match is a misconfiguration, not a valid no-op.

---

## 9. Architectural Decisions

_Record significant decisions here, or link to individual ADR files in `docs/adr/`._

| ID | Decision | Status | Date |
| :--- | :--- | :--- | :--- |
| [ADR-001](adr/0001-toml-config-format.md) | Use TOML for configuration file format (`labro.toml`) | Accepted | 2026-05-26 |
| [ADR-002](adr/0002-github-as-state-store.md) | Use GitHub labels as the state store for outcome tracking; universal `ai-contributed` marker label | Accepted | 2026-05-26 |
| [ADR-003](adr/0003-prompt-only-permitted-action-enforcement.md) | Prompt-only enforcement for permitted action set in v1; no `gh` wrapper script | Accepted | 2026-05-26 |
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

---

## 11. Risks & Technical Debt

| Risk | Likelihood | Impact | Mitigation |
| :--- | :--- | :--- | :--- |
| Agent takes actions outside permission envelope | Low–Medium | High | Prompt-only enforcement (v1); audit logs enable detection; `gh` wrapper as hard stop in v1.1 if needed. Risk accepted based on observed Claude Code instruction-following. |
| Agent self-reporting is unreliable | High | Medium | Accept for v1; track as metric; consider downstream outcome checks in v1.1. |
| SQLite file grows unboundedly | Low | Low | Add a periodic purge of run records older than N days before sustained operation. |
| `gh` CLI auth token expires | Medium | High | Monitor token expiry; surface in daily digest. |
| Runaway agent session costs | Medium | Medium | `--max-turns` for Claude Code CLI; configurable timeout for all agents. |

---

## Design Notes (WIP / TODO)

_Parking lot for decisions not yet formalised into the sections above._

### Prompt structure (`prompt_builder.py`)

Each prompt passed to the agent has four sections, in order:

1. **Role + harness context** — a short paragraph explaining that the agent is operating autonomously on behalf of Labro, on a schedule, with no human present. It should act decisively within its permitted actions or explicitly report that it cannot complete the task — it must not ask clarifying questions or wait for input.

2. **Task** — the task description from the task source. For `gh-delegated`: GitHub issue/PR title, body, and URL. For `grafana-alerts`: alert name, rule UID, severity, and current labels. For `proactive-improvement`: the selected improvement target and any strategy parameters.

3. **Permitted actions** — an explicit enumeration of the *GitHub write operations* the agent may and may not perform in this run (derived from the effective permitted action set). Scoped narrowly to side-effectful GitHub actions only — read operations, web searches, MCP tool calls (e.g. context7, web fetch), and local file operations are always unrestricted. Example: "You may: post a comment on a GitHub issue or PR, open a pull request. You must not: merge a pull request, approve a pull request, push directly to the default branch."

4. **Project context** — repo name, default branch, and an instruction to read `CLAUDE.md` at the repo root for project-specific conventions and constraints. Claude Code reads `CLAUDE.md` automatically when invoked in the repo directory; the prompt reinforces this as an explicit instruction. Any additional project-level context declared in `labro.toml` is appended here.

### `claude -p` structured output for agent result parsing

`claude -p` supports `--output-format json` combined with `--json-schema`, which causes the model to populate a `structured_output` field in the JSON response according to the provided schema. The top-level response also includes `total_cost_usd`, `num_turns`, `duration_ms`, and `usage` (token breakdown) — all directly usable for logging without parsing prose.

Example invocation:

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

Example top-level response shape (abridged):

```json
{
  "type": "result",
  "subtype": "success",
  "num_turns": 2,
  "total_cost_usd": 0.01439205,
  "duration_ms": 5250,
  "usage": {
    "input_tokens": 3,
    "output_tokens": 108,
    "cache_read_input_tokens": 41156,
    "cache_creation_input_tokens": 111
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

**Implication for the harness:** `runner.py` can parse the JSON response directly — no prose scraping needed. `logger.py` reads `total_cost_usd`, `num_turns`, `usage`, and `structured_output` verbatim into the SQLite run record.

The `items_created` field is the structured hook for outcome tracking: after the run, the harness writes one row to the `items_touched` table per entry in `items_created`. For `gh-delegated` tasks, the harness writes to `items_touched` at task-selection time (before the agent runs) since the item is already known. The daily digest job then queries `items_touched` and reads current GitHub state to populate outcome signals.

`actions_taken` remains a human-readable string array — used for the digest summary and the run record, not for outcome matching.

### Outstanding questions

_Unresolved gaps to address before implementation begins._

**Data models**

- **`Task` object** — `TaskSource.fetch_task()` returns `Task | None` but the `Task` dataclass is never defined. Minimum fields needed: `task_id`, `source`, `description`, `item_url` (nullable), `label_rule` / `actor_rule` reference (for post-run label transitions). Define before any task source module is written.
- **SQLite schema** — `store.py` has no `CREATE TABLE` statements anywhere. Three tables are implied: `runs`, `project_locks`, `items_touched`. Column types, indexes, and constraints need to be specified before `store.py` is implemented.

**Label state machine**

- The label lifecycle is described in prose across several sections but there is no single table or diagram showing: which labels trigger pickup per source, which are removed on completion, which are applied on failure, and which are mutually exclusive. A state-transition table per task source should be added to Section 5 or Section 8 before post_run.py is implemented.

**Digest spec**

- `digest.py` is named but its output format, Slack message structure, SQL queries, and firing schedule are unspecified. Minimum needed: which fields are aggregated, what the Slack message looks like, and how outcome signals (from `items_touched`) are surfaced vs. run-time stats.

**`entrypoint.sh` / crontab generation**

- The entrypoint reads `labro.toml` and writes `/etc/cron.d/labro`, but the generated format is unspecified. Open questions: does each project get one cron entry or two (run + digest)? What `PATH` and env vars does the generated crontab export? What user does the cron job run as inside the container?

**Dirty-repo recovery**

- The runtime view specifies `git reset --hard + git clean -fd` on a dirty working copy, but does not explain _why_ the repo would be dirty (agent crash mid-run while the lock was still held?). If the lock is held at crash time, the next run should hit the stale-lock path and log a warning — clarify whether dirty-repo recovery is a belt-and-suspenders guard or the primary recovery path, and document the expected sequence.

**`--json-schema` flag on `claude -p`**

- The structured output invocation in this document uses `--json-schema`. This flag name and behaviour should be verified against the current Claude Code CLI docs before `runner.py` is built around it. If the flag differs, the entire result-parsing strategy changes.

**Secret sanitisation**

- Section 8 states "agent output sanitised before persistence" but does not specify how. Options: regex against known token patterns, a deny-list of env var names, or stripping lines that match `GH_TOKEN`/`ANTHROPIC_API_KEY` patterns. Needs a concrete spec before `logger.py` is written.

**Outcome signal collection timing**

- The digest collects outcome signals from `items_touched` by reading current GitHub state. No minimum age is specified before collection runs. If a PR is merged within minutes of the run (e.g. operator was watching), it will be captured on the next digest — this is fine. But if the digest fires before the agent has finished (overlapping runs on different projects), `items_touched` may be incomplete. Clarify whether the digest job waits for all project locks to be clear before collecting signals, or collects signals only for runs completed before the digest window.
