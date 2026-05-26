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

_Brief restatement of what Labro is and the top 3–5 quality goals this architecture must satisfy. Reference the PRD rather than duplicating it._

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
| No external database (v1) | Operational simplicity; structured JSON log files are the initial persistence layer. |
| `gh` CLI for GitHub actions | Consistent auth model (`GH_TOKEN`); avoids a separate GitHub SDK dependency. |
| Claude Code CLI and Aider as v1 agents | Both are CLI-invocable; harness treats them as black boxes invoked via subprocess. |

---

## 3. System Context

_Who and what does Labro interact with? (C4 Level 1)_

```
┌─────────────────────────────────────────────────────────────────┐
│                         Operator                                │
│  (configures projects, reads daily digest, expands permissions) │
└────────────────────────────┬────────────────────────────────────┘
                             │ config + logs
                             ▼
                    ┌────────────────┐
                    │     Labro      │
                    │ (agent harness)│
                    └────┬──────┬───┘
                         │      │
              ┌──────────┘      └──────────┐
              ▼                            ▼
   ┌──────────────────┐        ┌───────────────────┐
   │   GitHub API     │        │   Grafana API     │
   │ (issues, PRs,    │        │ (firing alerts)   │
   │  labels, gh CLI) │        └───────────────────┘
   └──────────────────┘
              │
              ▼
   ┌──────────────────┐
   │  AI Agent CLI    │
   │ (Claude Code or  │
   │  Aider)          │
   └──────────────────┘
```

**External systems:**

| System | Role |
| :--- | :--- |
| GitHub | Source of tasks (issues, PRs, Dependabot); target of agent actions (comments, PRs, labels). |
| Grafana | Source of firing alert tasks. |
| Claude Code CLI | Agent: invoked for complex reasoning tasks. |
| Aider | Agent: invoked for lower-cost, simpler tasks. |
| Email / Slack | Delivery channel for daily digest. |

---

## 4. Container View

_Top-level deployable units. (C4 Level 2)_

```
┌──────────────────────────────────────────────────────────────┐
│  Docker Container                                            │
│                                                              │
│  ┌──────────────┐   ┌──────────────┐   ┌─────────────────┐  │
│  │   Scheduler  │   │    Harness   │   │   Agent CLIs    │  │
│  │  (cron/APSch │──▶│  (Python)    │──▶│  claude / aider │  │
│  │   eduler)    │   │              │   │  (subprocesses) │  │
│  └──────────────┘   └──────┬───────┘   └─────────────────┘  │
│                            │                                 │
│                    ┌───────▼───────┐                         │
│                    │  Log Store    │                         │
│                    │  (JSON files) │                         │
│                    └───────────────┘                         │
└──────────────────────────────────────────────────────────────┘
```

| Container | Technology | Responsibility |
| :--- | :--- | :--- |
| Scheduler | APScheduler or system cron | Fires harness runs per project on configured cron schedules; fires daily digest. |
| Harness | Python 3.12 | Task selection, prompt construction, agent invocation, label transitions, logging. |
| Agent CLIs | Claude Code CLI, Aider | Execute the task; interact with GitHub via `gh`; make code changes. |
| Log Store | JSON files on disk | Persist structured run logs; queried by digest and review CLI. |

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
├── prompt_builder.py Constructs agent prompt from task + permissions
├── agents/           Agent abstraction layer
│   ├── base.py       Abstract agent interface
│   ├── claude_code.py
│   └── aider.py
├── runner.py         Invokes agent subprocess; captures output
├── post_run.py       Label transitions; failure comments
├── logger.py         Structured JSON run logging
└── digest.py         Daily digest generation and delivery
```

### Key Interfaces

**TaskSource (base.py)**

```python
class TaskSource:
    def is_available(self, project: ProjectConfig) -> bool: ...
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
Picker iterates priority stack
    ├── TaskSource.is_available()?  No → next source
    └── TaskSource.fetch_task()?   None → next source
    │
    ▼
Task selected (or no task → run ends, logged as "skipped")
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
logger.py → write structured JSON run log
```

---

## 7. Deployment View

_How Labro is deployed and operated._

```
Host machine (single server or dev machine)
└── Docker container
    ├── /app/              Labro source code
    ├── /config/           labro.toml (bind-mounted from host)
    ├── /logs/             Run logs (bind-mounted from host)
    ├── /repos/            Cloned project repos (ephemeral or cached)
    └── env: GH_TOKEN, ANTHROPIC_API_KEY, GRAFANA_TOKEN, ...
```

* Container is built from a `Dockerfile` in the repo root.
* Config and logs live on the host via bind mounts (survives container restarts).
* Secrets are injected as environment variables (not baked into the image).
* Cron runs inside the container; no host-level cron required.

---

## 8. Cross-Cutting Concepts

### Security

* GitHub token scoped to minimum required permissions per project.
* Secrets never written to logs; agent output sanitised before persistence.
* Agent runs with file system access scoped to the cloned repo directory only.
* Permission envelope enforced at prompt-construction time (v1); runtime enforcement is a v1.1 goal.

### Observability & Logging

* Every run produces a structured JSON log entry regardless of outcome.
* Log fields: `run_id`, `project`, `task_source`, `task_description`, `agent`, `model`, `started_at`, `ended_at`, `duration_s`, `token_usage`, `turns_used`, `outcome` (`success` | `failure` | `skipped`), `actions_taken`, `failure_reason`.
* Daily digest aggregates across all projects: runs fired, tasks per source, skips, token spend, failures.
* Outcome signals (PR merged, issue closed, reactions) are read from GitHub state via the `ai-contributed` marker label — no sidecar index required. See [ADR-002](adr/0002-github-as-state-store.md).

### Error Handling

* Agent subprocess timeout → logged as failure; `ai-failed` label applied.
* Task source fetch failure → logged as warning; picker moves to next source.
* GitHub API errors → logged; run aborted cleanly.

### Configuration

* Single TOML file (`labro.toml`) declares all projects. Parsed with `tomllib` (stdlib); validated with Pydantic at startup. See [ADR-001](adr/0001-toml-config-format.md).
* Invalid config is a hard failure with a clear error message; no runs attempted.
* Config is the only file an operator needs to edit to add a project.

---

## 9. Architectural Decisions

_Record significant decisions here, or link to individual ADR files in `docs/adr/`._

| ID | Decision | Status | Date |
| :--- | :--- | :--- | :--- |
| [ADR-001](adr/0001-toml-config-format.md) | Use TOML for configuration file format (`labro.toml`) | Accepted | 2026-05-26 |
| [ADR-002](adr/0002-github-as-state-store.md) | Use GitHub labels as the state store for outcome tracking; universal `ai-contributed` marker label | Accepted | 2026-05-26 |

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
| New project added to config | Config change only | Project picked up on next scheduler cycle; no code change required. |

---

## 11. Risks & Technical Debt

| Risk | Likelihood | Impact | Mitigation |
| :--- | :--- | :--- | :--- |
| Agent takes actions outside permission envelope | Medium | High | Enforce at prompt level (v1); audit logs enable detection; runtime enforcement in v1.1. |
| Agent self-reporting is unreliable | High | Medium | Accept for v1; track as metric; consider downstream outcome checks in v1.1. |
| Log files grow unboundedly | Low | Low | Add log rotation (size/age) before sustained daily operation. |
| `gh` CLI auth token expires | Medium | High | Monitor token expiry; surface in daily digest. |
| Runaway agent session costs | Medium | Medium | `--max-turns` for Claude Code CLI; configurable timeout for all agents. |

---

## Design Notes (WIP / TODO)

_Parking lot for decisions not yet formalised into the sections above._

### `claude -p` structured output for agent result parsing

`claude -p` supports `--output-format json` combined with `--json-schema`, which causes the model to populate a `structured_output` field in the JSON response according to the provided schema. The top-level response also includes `total_cost_usd`, `num_turns`, `duration_ms`, and `usage` (token breakdown) — all directly usable for logging without parsing prose.

Example invocation:

```bash
echo "<prompt>" | claude -p \
  --output-format json \
  --json-schema '{
    "type": "object",
    "properties": {
      "outcome":         { "type": "string", "enum": ["success", "failure", "partial"] },
      "summary":         { "type": "string" },
      "actions_taken":   { "type": "array", "items": { "type": "string" } },
      "failure_reason":  { "type": "string" }
    },
    "required": ["outcome", "summary", "actions_taken"]
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
    "summary": "Reviewed PR #42 and left a comment requesting a change.",
    "actions_taken": ["gh pr review 42 --comment"],
    "failure_reason": null
  }
}
```

**Implication for the harness:** `runner.py` can parse the JSON response directly — no prose scraping needed. `logger.py` reads `total_cost_usd`, `num_turns`, `usage`, and `structured_output` verbatim into the run log. The `structured_output` schema effectively defines the contract between the harness and the agent for self-reporting. This significantly simplifies the "agent self-reporting is unreliable" risk — the schema enforces the shape of the report even if the content is still agent-generated.
