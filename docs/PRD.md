# PRD: Labro — Autonomous Agent Harness

* **Status:** Draft
* **Author:** Ross Arnold
* **Date:** 2026-05-26
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
| Human override rate (tasks needing correction) | — | TBD — track to reduce; captured via follow-up commits before merge (REQ-22) |

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
| **REQ-01** | As an operator, I want each project to have its own independently-configured cron schedule so different projects can run at different cadences with independent cost profiles. | P0 | Each project in config declares its own cron schedule; projects run independently and do not share a schedule. |
| **REQ-02** | As an operator, I want a deterministic Python script to select the highest-priority task so the agent always has clear, actionable work. | P0 | Script outputs a single task description; priority logic is readable and editable. |
| **REQ-03** | As an operator, I want to define the task priority stack in config (per project) so different projects and users can have different priorities without changing code. | P0 | Priority stack is an ordered list in the project config; the picker evaluates task sources top-to-bottom and takes the first match. |
| **REQ-04** | As an operator, I want built-in task source modules I can compose in my priority stack so I don't have to write sources from scratch. | P0 | Each task source is an independently loadable module; unused sources have zero cost. |
| **REQ-05** | As an operator, I want a `grafana-alerts` task source that detects currently-firing Grafana alerts and surfaces them as a task. | P0 | Polls Grafana API; returns highest-severity firing alert as task context. Agent behaviour for this source is triage and investigation: analyse the codebase and recent changes for likely cause, open a GitHub issue with findings, and raise a PR if a clear fix is identified. |
| **REQ-05a** | As an operator, I want repeated firings of the same alert to be deduplicated against existing GitHub issues so a long-running alert produces one tracked issue, not one per run. | P0 | Before acting, the source checks for an open Labro-created issue fingerprinting the same alert (matched via a per-rule label, e.g. `ai-alert:<rule-uid>`, written when the issue is opened). If a matching open issue exists, the source returns no task and the run logs `skipped: already tracking <issue#>`. GitHub issue state is the single source of truth for dedup — Labro does not write back to Grafana in v1. When the alert clears, Labro posts an "alert cleared" comment on the issue but leaves it open for the operator to close, so the close reason (REQ-22) remains a clean success signal. |
| **REQ-06** | As an operator, I want a `gh-delegated` task source that finds GitHub issues/PRs eligible for AI work via: (1) explicit labels (configurable list, e.g. `ai-analysis`, `ai-dev`, `ai-review`), and (2) implicit eligibility rules (configurable, e.g. "any open PR from `dependabot[bot]`"). | P0 | Config accepts a label list and an actor/origin allowlist; source returns all matching open items ranked by age or label precedence. Each label entry may declare its own permitted action override — e.g. `ai-dev` items get `open-pr` while `ai-review` items get `comment` only. This allows the operator to grant write access for development tasks without over-permitting review tasks. |
| **REQ-07** | As an operator, I want a `proactive-improvement` task source with a configurable target list and selection strategy so I control the scope of proactive work. | P1 | Config declares: (1) an ordered list of improvement targets, (2) a selection strategy (`agent-chooses` or `harness-random`), (3) a maximum open issue cap. If the number of open GitHub issues labelled `ai-proactive-suggestion` meets or exceeds the configured cap, the source returns no task and the harness skips agent invocation for this source. |
| **REQ-08** | As an operator, I want a configurable output mode for proactive improvement results so suggestions land where I want them. | P1 | Config selects output mode; v1 supports `gh-issue` (opens a GitHub issue), `email` (sends a summary), and `open-pr` (raises a PR where a concrete change is warranted). Whether `open-pr` is available is gated by the source's permitted actions; the agent raises a PR when it has a concrete, justified change and otherwise falls back to a suggestion. |

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
3. `proactive-improvement` — agent proposes something useful when no urgent work exists (output: GitHub issue, email, or PR where a concrete change is warranted) → Aider + cheap model

**Example permitted actions (Ross's first project):**

| Task Source | Permitted Actions |
| :--- | :--- |
| `grafana-alerts` | `comment`, `open-pr` — triage and surface findings; PR only if clear fix identified |
| `gh-delegated` | `comment` — Labro agents do not `approve` PRs in v1 (see note below) |
| `proactive-improvement` | `comment`, `open-pr` — suggest by default; raise a PR where a concrete, justified change exists |

> **v1 policy — no autonomous PR approval.** Labro agents may not `approve` PRs in v1/MVP, per Design Principle #5 (suggest over act). The `approve` action category still exists in the config schema (REQ-12) so it can be granted later once trust is established, but it is not enabled for any task source in v1.

### Epic B: Agent Execution

| ID | User Story | Priority | Acceptance Criteria |
| :--- | :--- | :--- | :--- |
| **REQ-09** | As an operator, I want to configure which agent and model to use at the task-source level (with a project-level default fallback) so I can route simpler tasks to cheaper agents and reserve more capable models for complex work. | P0 | Each task source in config optionally declares an agent and model; if absent, the project-level default applies. Config supports at minimum: Claude Code CLI and Aider, each with a configurable model parameter. |
| **REQ-10** | As an operator, I want the selected agent invoked with the constructed task prompt and its output captured so the harness can log outcomes regardless of which agent ran. | P0 | Harness abstracts agent invocation; stdout/stderr captured for all supported agents. |
| **REQ-11** | As an operator, I want the agent to have access to `gh` CLI commands so it can act on GitHub (comment, open PRs, push fixes). | P0 | `gh` is available in the container and authenticated via token. |
| **REQ-12** | As an operator, I want to define a permitted action set in config at both the project level and the task-source level so I control the blast radius of autonomous runs with fine-grained precision. | P0 | Config declares which action categories are enabled (e.g. `comment`, `approve`, `open-pr`, `merge`, `push`) at the project level as a default; each task source may optionally override with its own permitted action set. The harness communicates the effective permitted actions to the agent before invocation. |
| **REQ-13** | As an operator, I want the agent to run in a sandboxed environment so mistakes don't affect my main dev environment. | P1 | Agent runs inside Docker; file system access scoped to cloned repo. |

### Epic B2: Task State Management

| ID | User Story | Priority | Acceptance Criteria |
| :--- | :--- | :--- | :--- |
| **REQ-20** | As an operator, I want the harness to transition GitHub labels as a deterministic post-run step so task state is always consistent and items are not re-selected on future runs. | P0 | On successful completion: harness applies the configured done label (e.g. `ai-dev-done`) and removes the source label. On failure: harness applies `ai-labro-failed` and posts a comment with the agent's self-reported failure reason. Label transitions are configured per task source. |
| **REQ-21** | As an operator, I want Labro to send a single daily digest across all configured projects so I can assess system health without manually inspecting logs. | P1 | Digest fires once per day on a fixed schedule (independent of any project's cron). Delivered via email or Slack (configurable). Content covers all projects in a single summary: runs fired, tasks selected per source, tasks skipped (and why), token spend, and any failure labels applied. Digest is a health and cost signal — not a duplicate of ambient GitHub/Slack notifications generated by agent actions. |

### Epic C: Observability & Logging

| ID | User Story | Priority | Acceptance Criteria |
| :--- | :--- | :--- | :--- |
| **REQ-14** | As an operator, I want each run logged with: task type, task description, agent and model used, start/end time, token usage, rounds used, and agent self-reported outcome. | P0 | Structured log written per run. |
| **REQ-15** | As an operator, I want to know whether the agent believed it succeeded and what actions it took (e.g. "opened PR #42", "pushed commit abc123"). | P0 | Agent output parsed for action summary; stored alongside run log. |
| **REQ-16** | As an operator, I want a simple way to review recent runs so I can spot failures or bad behaviour quickly. | P1 | CLI command or script to tail/summarize recent run logs. |
| **REQ-17** | As an operator, I want token and time costs aggregated by agent and model so I can understand and control spend. | P1 | Daily/weekly summary queryable from logs; broken down by agent/model. |
| **REQ-22** | As an operator, I want Labro to capture *outcome* signals for past tasks from passive GitHub state so I can judge real usefulness without manual bookkeeping. | P0 | On each run, for items acted on in prior runs, Labro reads native GitHub state — PR merged vs. closed-unmerged, issue close reason (`completed` vs. `not planned`), and whether the operator added commits to an AI-opened PR before merge — and records each as an outcome signal against the original run log. |
| **REQ-23** | As an operator, I want to express explicit satisfaction with a single click so I can correct or confirm Labro's self-reported success cheaply. | P1 | Labro reads 👍/👎 reactions on its own issue/PR comments via the GitHub API and records them as a satisfaction signal against the originating run. The daily digest (REQ-21) includes an "awaiting your verdict" section listing recently-acted items with direct links, so the reaction prompt rides on the existing digest rather than a separate notification. |

**Success signal model**

Labro distinguishes three signals; only the first is available at run time, so the digest reports satisfaction for *previous* runs, never the current one.

| Signal | Type | Source | Operator effort | Interpretation |
| :--- | :--- | :--- | :--- | :--- |
| Agent self-report | leading, subjective | agent output (REQ-15) | none | "the agent believed it succeeded" — a hint, not ground truth |
| PR merged / issue closed | lagging, objective | native GitHub state (REQ-22) | zero (normal review) | the work survived contact with the operator |
| Issue closed `not planned` | lagging, objective | native GitHub state (REQ-22) | one click | the task was noise |
| Follow-up commits before merge | lagging, objective | native GitHub state (REQ-22) | zero | needed correction → feeds **human override rate** KPI |
| 👍 / 👎 reaction | lagging, subjective | GitHub reactions API (REQ-23) | one click | explicit operator sentiment |

Labels remain reserved for Labro's own lifecycle state (REQ-20); human sentiment is captured via reactions and close-reason, not labels, to keep the two families from colliding in the UI.

### Epic D: Configuration & Project Support

| ID | User Story | Priority | Acceptance Criteria |
| :--- | :--- | :--- | :--- |
| **REQ-18** | As an operator, I want to configure which GitHub repos Labro monitors, with per-project cron schedules, priority stacks, permitted actions, and a default agent/model that individual task sources can override. | P0 | Config file supports multiple projects; each project declares its own cron schedule, a default agent/model, default permitted actions, and an ordered task source list where each source may optionally override the agent/model and permitted actions. |
| **REQ-19** | As an operator, I want to be able to add a new project to Labro with minimal effort. | P1 | Adding a repo requires only config changes, no code changes. |

*(Priority Scale: P0 = Critical/Launch blocking, P1 = Important/Should have, P2 = Nice to have)*

---

## User Experience & Interface

Labro is a headless, operator-facing tool. There is no end-user UI.

* **Operator interface:** Config file + structured log files + daily digest.
* **Operator touchpoints:** Two distinct channels surface Labro's activity:
  * **Daily digest (async, pull):** Email or Slack summary of runs, task selections, skips, costs, and failures. This is the primary "is this working?" signal — health and cost visibility, not action replay.
  * **Ambient notifications (real-time, push):** Agent actions on GitHub and Slack generate their own notifications (GitHub mentions, issue assignments, PR activity, Slack namechecks). These are not mediated by Labro; they surface through the operator's normal channels.
* **Trust expansion:** Permitted actions are expanded manually by the operator, informed by observability data. Labro does not prompt for permission upgrades.
* **Key operator flow:**
  1. Operator adds a repo to config with a cron schedule, priority stack, and per-source permitted actions
  2. Cron triggers task picker for that project
  3. Task picker evaluates priority stack and selects highest-priority task
  4. Agent is invoked with constructed prompt (scoped to effective permitted actions)
  5. Agent executes (gh commands, git operations)
  6. Harness performs label transitions (success → done label; failure → `ai-labro-failed` + comment)
  7. Run result and action summary logged
  8. Operator receives daily digest summarising health and spend

---

## Technical & Constraints

* **Runtime:** Docker container; Python 3.12+.
* **Supported agents (v1):** Claude Code CLI (`claude -p`) and [Aider](https://aider.chat/). Both are invoked via CLI with a constructed prompt; the harness abstracts the difference. Agent and model are configurable per project and optionally per task source.
* **GitHub integration:** `gh` CLI, authenticated via `GH_TOKEN` environment variable.
* **Scheduling:** Cron inside the Docker container, configurable frequency (default: hourly).
* **Logging format:** Structured JSON logs per run; stored as files initially (no external log sink required for v1).
* **Security/Privacy:** GitHub token scoped to minimum required permissions. No secrets stored in logs. Agent output sanitised before logging.
* **Performance:** Each run should complete within a configurable timeout and/or maximum turn count to prevent runaway agent sessions consuming excessive tokens. Where the agent supports it (e.g. Claude Code CLI's `--max-turns`), turn limiting is preferred as it bounds cost more precisely than time alone.
* **Spend control (v1 decision):** Per-run bounds (timeout, `--max-turns`) cap a single run, but v1 deliberately has **no aggregate budget cap** that halts runs across a day/week. Spend is observe-only — captured and surfaced in logs and the daily digest (REQ-17, REQ-21) — on the basis that per-run caps plus daily visibility are sufficient for a single operator's projects. An aggregate spend ceiling is a candidate for a later version if observed cost warrants it.
* **Dependencies:** Claude Code CLI (`claude`) must be available and authenticated in the container.
* **Monitoring integration (v1):** Grafana alerts via Grafana HTTP API. Other alert sources (PagerDuty, Uptime Robot, etc.) are out of scope for v1 but the task source module interface should not preclude them.

---

## Open Questions / Risks

* [x] **Resolved:** How should real task success be measured beyond agent self-reporting? **Decision:** v1 uses a passive-first signal model (see [Success signal model](#epic-c-observability--logging), REQ-22/REQ-23). Ground truth comes from native GitHub state Labro reads on subsequent runs — PR merged, issue close reason, and follow-up commits before merge — which require no operator bookkeeping. Explicit satisfaction is captured via 👍/👎 reactions, prompted inside the daily digest rather than a separate reminder. Agent self-report is retained as a leading hint only. Open follow-on: tune how many runs/hours to wait before treating a "no outcome yet" item as inconclusive.
* [ ] **Risk:** Agent may take actions outside the configured permission set. v1 enforces permissions at invocation time only — track violations in observability logs and consider runtime enforcement in v1.1.

