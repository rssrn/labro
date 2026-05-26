# PRD: Labro — Autonomous Agent Harness

* **Status:** Draft
* **Author:** Ross Arnold
* **Date:** 2026-05-25
* **Target Release:** Continuous / no fixed date

---

## Executive Summary

Labro is a self-hosted agent harness that runs AI coding agents on a schedule to do useful, unsupervised work on software projects — triaging issues, reviewing PRs, fixing bugs, and proposing improvements. Named after cleaner wrasse fish stations on coral reefs (_Labroides dimidiatus_), which provide a designated, high-value, symbiotic service to reef inhabitants, Labro acts as an always-available autonomous worker that keeps projects healthy with minimal human supervision. The operator chooses which agent and model to use per project or task type, enabling cost-conscious decisions such as routing simpler tasks to a cheaper model via Aider while reserving more capable (and expensive) models for complex work.

---

## Design Principles

These principles govern every product decision in Labro. When requirements conflict, apply these to resolve the tension.

* **Configuration over convention.** Labro ships no hardcoded opinions about task priority, permitted actions, or improvement targets. Everything that could reasonably vary between users or projects is expressed in config, not code.
* **The harness is an envelope, not an agent.** Labro's job is to select a task, construct a well-scoped prompt, invoke the agent, and record the result. It does not attempt to be smart; the agent is smart. The harness is deterministic and auditable.
* **Observability is a first-class feature.** Every run is logged in enough detail to reconstruct what happened, why the task was selected, what actions the agent took, and at what cost. This data is the primary feedback loop for improving Labro over time.
* **Start narrow, stay extensible.** v1 targets a single user's projects. Architecture decisions (task source modules, action permission categories, output modes) should not require code changes to support a new project or user — only config changes.
* **Lightweight by default.** Prefer lower-autonomy defaults (suggest over act, comment over merge) so operators build trust in the system before granting more permissions.

---

## Problem Statement & "Why"

* **The Problem:** Software projects — especially those maintained by solo developers or small teams — accumulate a constant backlog of valuable but non-urgent work: Dependabot PRs sitting unreviewed, TODO comments that never get triaged, production anomalies that go uninvestigated until they become incidents, and improvement opportunities that never surface because there's always something more pressing. Capable AI agents can now handle much of this work autonomously, but general-purpose tools don't provide the configurable, project-aware task selection and observability layer needed to run them safely and usefully on a schedule.
* **Evidence:** The gap is not agent capability — it's orchestration. Claude Code and similar tools can already review PRs, investigate alerts, and propose fixes. What's missing is the layer that decides *what* to work on given a specific project's priorities, invokes the agent with the right context and permission envelope, and records what happened in enough detail to build trust over time. See [Existing Landscape](#existing-landscape--competitive-context).
* **Value Proposition:** Labro converts idle compute time into a continuous, low-noise maintenance service for software projects. For the operator, this means fewer things falling through the cracks, faster responses to production issues, and a growing body of agent-authored work that would otherwise never get done. Because the harness is configurable rather than opinionated, it compounds in value as operators tune it to their project's specific needs and expand agent permissions as trust is established.

---

## Existing Landscape & Competitive Context

Several tools exist in this space. None were disqualifying — the rationale for Labro is differentiation, not novelty.

| Tool | Description | Where it falls short for Labro's use case |
| :--- | :--- | :--- |
| [OpenHands](https://www.openhands.dev/) (formerly OpenDevin) | Self-hostable, open-source autonomous software engineering agent. Strong SWE-Bench performance; supports many LLM providers; has a web UI and cloud offering. | General-purpose software engineering focus; no built-in concept of project-specific task priority stacks, alert sources, or per-project permission envelopes. Heavyweight for personal project maintenance. |
| [Cline](https://cline.bot/) | Open-source AI coding agent (VS Code extension + CLI). Explicitly supports running in cron jobs and CI pipelines. | Designed for interactive use; no task-selection layer, observability, or project config model out of the box. |
| [GitHub Agentic Workflows](https://blog.codeinside.eu/2026/05/11/github-agentic-workflows/) | Uses GitHub Actions as the scheduling and event-trigger layer for AI agents. | Tightly coupled to GitHub's infrastructure; no persistent task-selection logic or cross-repo observability. Each workflow is independent. |
| [Autobot](https://veelenga.github.io/how-agent-loop-and-cron-work-together-inside-autobot/) | Agent framework with built-in cron scheduling; routes scheduled tasks through the same message bus as interactive agent sessions. | General agent loop rather than a software project maintenance harness. |
| [CronBox](https://www.producthunt.com/products/cronbox-2) | Cloud product specifically for scheduling AI agents on a cron basis. | Cloud-hosted (not self-hosted); closed product; no software project-specific integrations (GitHub, Grafana, etc.). |

**Labro's differentiation:** a lightweight, self-hosted harness with a configurable, project-aware task-selection layer; per-project permission envelopes; and first-class observability — purpose-built for personal software project maintenance rather than general software engineering.

---

## Goals & Success Metrics

### Business Goals
* **Steady-state usefulness:** Labro runs daily on at least one real project, completing tasks without requiring operator intervention most of the time.
* **Trust-building signal:** Observability data is sufficient to make an informed decision about whether and when to expand agent permissions — the logs should answer "is this working?" without manual inspection of agent output.
* **Zero-config project addition:** Onboarding a new project requires only a config change; no code changes to the harness.
* **Cost awareness:** Token and time costs per task are captured and queryable, so the operator can make informed decisions about run frequency, task scope, and agent model selection.

### Non-Goals (Out of Scope for v1)
* Multi-user or team features — Labro is personal tooling first.
* A web UI or dashboard — observability via logs/files initially.
* Support for agents beyond Claude Code CLI and Aider — architecture should allow others later, but these two are the v1 targets.
* Real-time event-driven triggering — cron scheduling is sufficient for v1.
* Mobile notifications or alerting integrations.

### Key Performance Indicators (KPIs)

| Metric | Current State | Target (after 4 weeks of operation) |
| :--- | :--- | :--- |
| Tasks completed per week | 0 (not yet running) | TBD — baseline first |
| Agent success rate (self-reported) | — | TBD |
| Token cost per task | — | TBD |
| Human override rate (tasks needing correction) | — | TBD — track to reduce |

> _KPI targets intentionally left open until baseline data is collected._

---

## Target Audience & Personas

* **Primary Persona:** Ross (solo developer) — runs multiple personal projects on GitHub, wants routine maintenance to happen autonomously without context-switching.
* **Future Persona:** Other solo developers or small teams who want an autonomous agent harness they can self-host and configure for their own repos.

---

## User Stories & Functional Requirements

### Epic A: Task Selection & Scheduling

| ID | User Story | Priority | Acceptance Criteria |
| :--- | :--- | :--- | :--- |
| **REQ-01** | As an operator, I want a cron-triggered run (e.g. hourly) so the agent works without manual intervention. | P0 | Docker container with configurable cron schedule. |
| **REQ-02** | As an operator, I want a deterministic Python script to select the highest-priority task so the agent always has clear, actionable work. | P0 | Script outputs a single task description; priority logic is readable and editable. |
| **REQ-03** | As an operator, I want to define the task priority stack in config (per project) so different projects and users can have different priorities without changing code. | P0 | Priority stack is an ordered list in the project config; the picker evaluates task sources top-to-bottom and takes the first match. |
| **REQ-04** | As an operator, I want built-in task source modules I can compose in my priority stack so I don't have to write sources from scratch. | P0 | Each task source is an independently loadable module; unused sources have zero cost. |
| **REQ-05** | As an operator, I want a `grafana-alerts` task source that detects currently-firing Grafana alerts and surfaces them as a task. | P0 | Polls Grafana API; returns highest-severity firing alert as task context. |
| **REQ-06** | As an operator, I want a `gh-delegated` task source that finds GitHub issues/PRs eligible for AI work via: (1) explicit labels (configurable list, e.g. `ai-analysis`, `ai-dev`, `ai-review`), and (2) implicit eligibility rules (configurable, e.g. "any open PR from `dependabot[bot]`"). | P0 | Config accepts a label list and an actor/origin allowlist; source returns all matching open items ranked by age or label precedence. |
| **REQ-07** | As an operator, I want a `proactive-improvement` task source with a configurable target list and selection strategy so I control the scope of proactive work. | P1 | Config declares: (1) an ordered list of improvement targets, (2) a selection strategy (`agent-chooses` or `harness-random`). |
| **REQ-08** | As an operator, I want a configurable output mode for proactive improvement results so suggestions land where I want them. | P1 | Config selects output mode; v1 supports `gh-issue` (opens a GitHub issue) and `email` (sends a summary). Opening a PR is out of scope for this source in v1. |

**Proactive improvement: selection strategies**

| Strategy | Behaviour |
| :--- | :--- |
| `agent-chooses` | The full target list is passed to the agent in the prompt; the agent selects the most relevant target given current project state and explains its choice. |
| `harness-random` | The harness picks one target at random from the list and passes only that target to the agent. Simpler, more varied over time. |

**Built-in improvement targets (operator selects a subset in config):**

| Target | Description |
| :--- | :--- |
| `review-app-logs` | Scan application logs from the last N hours for anomalies, errors, or trends |
| `review-prometheus-metrics` | Review Prometheus/Grafana metrics from the last N hours for regressions or anomalies |
| `competitor-analysis` | Feature-focused analysis of a configurable list of competing products |
| `architecture-review` | High-level review of the codebase architecture; identify coupling, missing abstractions, scalability concerns |
| `security-review` | Scan for common security issues, exposed secrets, or outdated vulnerable dependencies |
| `test-coverage-review` | Identify untested or under-tested code paths; suggest or write missing tests |
| `scan-todos` | Find TODO/FIXME/HACK comments in the codebase and triage them |
| `surprise-me` | Agent selects its own focus area with no constraint — open-ended exploration |

**Example priority stack (Ross's first project):**
1. `grafana-alerts` — firing production alert → Claude Sonnet (needs reasoning and context)
2. `gh-delegated` — issues/PRs labelled `ai-analysis`, `ai-dev`, or `ai-review`; OR opened by `dependabot[bot]` → Aider + cheap model for Dependabot; Claude for labelled issues
3. `proactive-improvement` — agent proposes something useful when no urgent work exists (output: GitHub issue or email; not a PR) → Aider + cheap model

**Example permitted actions (Ross's first project):** `comment`, `approve` — no merge, no push to main.

### Epic B: Agent Execution

| ID | User Story | Priority | Acceptance Criteria |
| :--- | :--- | :--- | :--- |
| **REQ-09** | As an operator, I want to configure which agent and model to use at the task-source level (with a project-level default fallback) so I can route simpler tasks to cheaper agents and reserve more capable models for complex work. | P0 | Each task source in config optionally declares an agent and model; if absent, the project-level default applies. Config supports at minimum: Claude Code CLI and Aider, each with a configurable model parameter. |
| **REQ-10** | As an operator, I want the selected agent invoked with the constructed task prompt and its output captured so the harness can log outcomes regardless of which agent ran. | P0 | Harness abstracts agent invocation; stdout/stderr captured for all supported agents. |
| **REQ-11** | As an operator, I want the agent to have access to `gh` CLI commands so it can act on GitHub (comment, open PRs, push fixes). | P0 | `gh` is available in the container and authenticated via token. |
| **REQ-12** | As an operator, I want to define a permitted action set in config (per project) so I control the blast radius of autonomous runs. | P0 | Config declares which action categories are enabled (e.g. `comment`, `approve`, `open-pr`, `merge`, `push`). The harness communicates permitted actions to the agent before invocation (via prompt, CLI args, or agent config — whichever is appropriate for the agent in use). |
| **REQ-13** | As an operator, I want the agent to run in a sandboxed environment so mistakes don't affect my main dev environment. | P1 | Agent runs inside Docker; file system access scoped to cloned repo. |

### Epic C: Observability & Logging

| ID | User Story | Priority | Acceptance Criteria |
| :--- | :--- | :--- | :--- |
| **REQ-14** | As an operator, I want each run logged with: task type, task description, agent and model used, start/end time, token usage, rounds used, and agent self-reported outcome. | P0 | Structured log written per run. |
| **REQ-15** | As an operator, I want to know whether the agent believed it succeeded and what actions it took (e.g. "opened PR #42", "pushed commit abc123"). | P0 | Agent output parsed for action summary; stored alongside run log. |
| **REQ-16** | As an operator, I want a simple way to review recent runs so I can spot failures or bad behaviour quickly. | P1 | CLI command or script to tail/summarize recent run logs. |
| **REQ-17** | As an operator, I want token and time costs aggregated by agent and model so I can understand and control spend. | P1 | Daily/weekly summary queryable from logs; broken down by agent/model. |

### Epic D: Configuration & Project Support

| ID | User Story | Priority | Acceptance Criteria |
| :--- | :--- | :--- | :--- |
| **REQ-18** | As an operator, I want to configure which GitHub repos Labro monitors, with per-project priority stacks, permitted actions, and a default agent/model that individual task sources can override. | P0 | Config file supports multiple projects; each project declares a default agent/model and an ordered task source list where each source may optionally override the agent/model. |
| **REQ-19** | As an operator, I want to be able to add a new project to Labro with minimal effort. | P1 | Adding a repo requires only config changes, no code changes. |

*(Priority Scale: P0 = Critical/Launch blocking, P1 = Important/Should have, P2 = Nice to have)*

---

## User Experience & Interface

Labro is a headless, operator-facing tool. There is no end-user UI.

* **Operator interface:** Config file + structured log files.
* **Key operator flow:**
  1. Operator adds a repo to config
  2. Cron triggers task picker
  3. Task picker evaluates priority stack and selects highest-priority task
  4. Agent is invoked with constructed prompt (scoped to permitted actions)
  5. Agent executes (gh commands, git operations)
  6. Run result and action summary logged
  7. Operator optionally reviews log summary

---

## Technical & Constraints

* **Runtime:** Docker container; Python 3.12+.
* **Supported agents (v1):** Claude Code CLI (`claude -p`) and [Aider](https://aider.chat/). Both are invoked via CLI with a constructed prompt; the harness abstracts the difference. Agent and model are configurable per project and optionally per task source.
* **GitHub integration:** `gh` CLI, authenticated via `GH_TOKEN` environment variable.
* **Scheduling:** Cron inside the Docker container, configurable frequency (default: hourly).
* **Logging format:** Structured JSON logs per run; stored as files initially (no external log sink required for v1).
* **Security/Privacy:** GitHub token scoped to minimum required permissions. No secrets stored in logs. Agent output sanitised before logging.
* **Performance:** Each run should complete within a configurable timeout and/or maximum turn count to prevent runaway agent sessions consuming excessive tokens. Where the agent supports it (e.g. Claude Code CLI's `--max-turns`), turn limiting is preferred as it bounds cost more precisely than time alone.
* **Dependencies:** Claude Code CLI (`claude`) must be available and authenticated in the container.
* **Monitoring integration (v1):** Grafana alerts via Grafana HTTP API. Other alert sources (PagerDuty, Uptime Robot, etc.) are out of scope for v1 but the task source module interface should not preclude them.

---

## Open Questions / Risks

* [ ] **Question:** How should real task success be measured beyond agent self-reporting? Self-reporting is a useful signal but not ground truth — a PR the agent approved may never get merged, or a bug it "fixed" may recur. Options: (a) a follow-up check run N hours later that looks for downstream outcomes (PR merged, issue closed); (b) accept self-reporting for v1 and treat it as a metric to validate manually during early operation.
* [ ] **Risk:** Agent may take actions outside the configured permission set. v1 enforces permissions at invocation time only — track violations in observability logs and consider runtime enforcement in v1.1.
