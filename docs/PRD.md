# PRD: Labro — Autonomous Agent Harness

* **Status:** Draft
* **Author:** Ross Arnold
* **Date:** 2026-05-26
* **Target Release:** Continuous / no fixed date

---

## Executive Summary

Labro is a self-hosted agent harness that runs AI coding agents on a schedule to do useful, unsupervised work on software projects — triaging issues, reviewing PRs, fixing bugs, and proposing improvements. Named after cleaner wrasse fish stations on coral reefs (_Labroides dimidiatus_), which provide a designated, high-value, symbiotic service to reef inhabitants, Labro acts as an always-available autonomous worker that keeps projects healthy with minimal human supervision. The operator chooses which model to use per project or task type, enabling cost-conscious decisions such as routing simpler tasks to a cheaper model while reserving more capable (and expensive) models for complex work.

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

Several tools exist in this space. None were disqualifying — the rationale for Labro is differentiation, not novelty. For the full competitive analysis and the case for self-build, see [docs/CASE-FOR-SELF-BUILD.md](CASE-FOR-SELF-BUILD.md).

**PR-review bots (reactive, event-driven)**

| Tool | Description | Where it falls short for Labro's use case |
| :--- | :--- | :--- |
| [PR-Agent](https://github.com/The-PR-Agent/pr-agent) (formerly Qodo Merge; Apache 2.0, community-owned 2025) | AI-powered PR review, summarisation, and suggestions. Self-hostable with your own LLM keys. Supports GitHub, GitLab, Bitbucket, Azure DevOps. | No task selection layer, no scheduling, no proactive work, no alert integration, no permission envelopes, no outcome tracking. Event-driven (PR webhook) rather than cron/pull-based. |
| [Sweep AI](https://docs.sweep.dev/) | GitHub issue → autonomous PR. Labels an issue; Sweep plans, commits, and opens a PR ready for review. Apache 2.0. | Effectively abandoned as a self-hosted harness (pivoted to JetBrains plugin). No scheduling, no priority queue, narrow issue→PR only. |
| [GitHub Agentic Workflows](https://github.blog/changelog/2026-02-13-github-agentic-workflows-are-now-in-technical-preview/) | Event-driven AI agents within GitHub Actions: issue triage, PR review, CI failure analysis. | Tightly coupled to GitHub infrastructure; each workflow is independent; no cross-repo priority logic; no persistent observability. |

**General autonomous coding agents (no scheduling or selection layer)**

| Tool | Description | Where it falls short for Labro's use case |
| :--- | :--- | :--- |
| [OpenHands](https://www.openhands.dev/) (formerly OpenDevin) | Full-stack autonomous software engineering platform. Strong SWE-Bench performance; web UI; multi-user; Kubernetes-ready. Two-tier deployment: long-lived app container + per-task sandbox containers spawned via Docker socket. RFC for scheduled automations [in progress](https://github.com/OpenHands/OpenHands/issues/13275). | No task selection or priority layer; no Grafana integration; no per-source permission envelopes; heavyweight deployment model (multi-service, requires Docker socket, web UI) relative to personal project maintenance. Scheduled RFC unshipped. |
| [SWE-agent](https://swe-agent.com/latest/) (Princeton) | Research-focused; custom Agent-Computer Interface; designed for GitHub issue → automated fix. MIT licence. | Research tool, not a harness; no scheduling, no task prioritisation, no observability, no permission model. |
| [Cline](https://cline.bot/) | Open-source AI coding agent (VS Code extension + CLI). Explicitly supports running in cron jobs and CI pipelines. | Designed for interactive use; no task-selection layer, observability, or project config model out of the box. |

**Cron/scheduled agent platforms (general-purpose, not project-maintenance)**

| Tool | Description | Where it falls short for Labro's use case |
| :--- | :--- | :--- |
| [OpenClaw](https://docs.openclaw.ai/automation/cron-jobs) | Lightweight self-hosted personal AI assistant with cron scheduling and 50+ messaging platform integrations. Cron jobs run in isolated sessions with their own model and context. | Chat-agent architecture, not a software maintenance harness; no project-aware priority lists; no multi-source task selection; no outcome tracking; no permission envelopes. |
| [Autobot](https://veelenga.github.io/how-agent-loop-and-cron-work-together-inside-autobot/) | Agent framework with built-in cron scheduling; routes scheduled tasks through the same message bus as interactive agent sessions. | General agent loop; no software-project-specific integrations (GitHub, Grafana); no observability. |
| [CronBox](https://www.producthunt.com/products/cronbox-2) | Cloud product specifically for scheduling AI agents on a cron basis. | Cloud-hosted (not self-hosted); closed product; no software project-specific integrations (GitHub, Grafana, etc.). |

**Issue triage specialists (narrow scope)**

| Tool | Description | Where it falls short for Labro's use case |
| :--- | :--- | :--- |
| [trIAge](https://github.com/trIAgelab/trIAge) | LLM-powered issue triage, labelling, and user support for open-source communities; deployable as a self-hosted GitHub App. | Triage only — no code changes, no PRs, no alert integration, no proactive improvement. Aimed at open-source maintainer communities, not solo devs. |

**Labro's differentiation:** a lightweight, self-hosted harness with a configurable, project-aware task-selection layer; per-project, per-source permission envelopes; first-class observability with passive outcome signal tracking; and a Grafana alert pipeline — purpose-built for personal software project maintenance rather than general software engineering. See [CASE-FOR-SELF-BUILD.md](CASE-FOR-SELF-BUILD.md) for the full analysis.

---

## Goals & Success Metrics

### Business Goals
* **Framework adds value:** Labro runs daily on at least one real project and produces work the operator judges worth keeping. Success is measured by accepted output — not by whether the operator ever expands agent permissions. A human-in-the-loop deployment where every action is reviewed before merge is a fully successful outcome.
* **Answers "is this working?" without manual inspection:** Observability data is sufficient to judge whether Labro is adding value from the digest and logs alone, without reading raw agent output. (Whether this confidence later leads an operator to expand permissions is optional and operator-driven, not a goal of the system.)
* **Zero-config project addition:** Onboarding a new project requires only a config change; no code changes to the harness.
* **Cost awareness:** Token and time costs per task are captured and queryable, so the operator can make informed decisions about run frequency, task scope, and agent model selection.

### Non-Goals (Out of Scope for v1)
* Multi-user or team features — Labro is personal tooling first.
* A web UI or dashboard — observability via logs/files initially.
* Support for agents beyond Claude Code CLI — architecture should allow others later, but Claude Code is the sole v1 target.
* Real-time event-driven triggering — deliberately omitted, not deferred. A webhook fires immediately on a single event with no awareness of competing priorities; it would routinely spend budget on the lowest-priority item in the system (e.g. a trivial Dependabot PR) while a higher-priority task waits. Cron + priority picker is the intentional model: the picker evaluates all sources at run time and routes budget to the highest-priority work. For cases where latency matters (e.g. a firing Grafana alert), the cron interval is configurable per project — the scheduler can be tightened without adding architectural complexity.
* Mobile notifications or alerting integrations.

### Key Performance Indicators (KPIs)

The **baseline window** is the first 4 weeks of continuous operation on at least one real project. Three headline metrics define "is the framework adding value?" — each targets **75%** over the baseline window. They are deliberately independent: the objective metric measures whether work lands, the sentiment metric measures whether the operator likes it, and the self-report metric measures whether our prompts are sound.

| Metric | Source | Current State | Target (baseline window) |
| :--- | :--- | :--- | :--- |
| **PR merge rate** (objective acceptance) — AI-opened PRs merged ÷ AI-opened PRs closed | native GitHub state (REQ-22) | 0 (not yet running) | ≥ 75% merged |
| **Satisfaction ratio** (explicit sentiment) — 👍 ÷ (👍 + 👎) on Labro comments | GitHub reactions (REQ-23) | — | ≥ 75% positive |
| **Agent completion reported success rate** (prompt quality) — runs the agent reports as success ÷ all runs | agent output (REQ-15) | — | ≥ 75% success |

Self-reported success is *not* a measure of real usefulness (it is a leading, subjective hint — see the Success Signal Model table in the Functional Requirements section); it is tracked here specifically as a signal of whether the harness's prompts and task scoping are working — including whether operators are labelling up tasks of appropriate complexity for the agent (over-scoped tasks the agent cannot complete will depress this rate). A low self-report rate points at the harness or at task selection; a high self-report rate paired with a low merge rate points at agent quality.

**Supporting metrics (tracked for diagnosis and cost control, no fixed target in v1):**

| Metric | Source |
| :--- | :--- |
| Tasks completed per week (throughput) | run logs (REQ-14) |
| Tasks selected vs. skipped, per source (which sources actually fire) | run logs (REQ-21) |
| Human override rate — follow-up commits on AI PRs before merge | native GitHub state (REQ-22) |
| Issue close reason: `completed` vs. `not planned` (useful vs. noise) | native GitHub state (REQ-22) |
| Failure rate — `ai-failed` labels applied | run logs (REQ-20) |
| Token cost per task and per accepted outcome, by agent/model | run logs (REQ-17) |

> _The three 75% headline targets are initial judgement calls, not baselined figures; revisit after the first baseline window with real data._

---

## Target Audience & Personas

* **Primary Persona:** Ross (solo developer) — runs multiple personal projects on GitHub, wants routine maintenance to happen autonomously without context-switching.
* **Future Persona:** Other solo developers or small teams who want an autonomous agent harness they can self-host and configure for their own repos.

---

## User Stories & Functional Requirements

| ID | User Story | Priority | Acceptance Criteria |
| :--- | :--- | :--- | :--- |
| **REQ-01** | As an operator, I want each project to have its own independently-configured cron schedule so different projects can run at different cadences with independent cost profiles. | P0 | Each project in config declares its own cron schedule; projects run independently and do not share a schedule. |
| **REQ-02** | As an operator, I want a deterministic Python script to select the highest-priority task so the agent always has clear, actionable work. | P0 | Script outputs a single task description; priority logic is readable and editable. |
| **REQ-03** | As an operator, I want to define the task priority list in config (per project) so different projects and users can have different priorities without changing code. | P0 | Priority list is an ordered list in the project config; the picker evaluates task sources top-to-bottom and takes the first match. |
| **REQ-04** | As an operator, I want built-in task source modules I can compose in my priority list so I don't have to write sources from scratch. | P0 | Each task source is an independently loadable module; unused sources have zero cost. |
| **REQ-05** | As an operator, I want a `grafana-alerts` task source that detects currently-firing Grafana alerts and surfaces them as a task. | P0 | Polls Grafana API; returns highest-severity firing alert as task context. Agent behaviour for this source is triage and investigation: analyse the codebase and recent changes for likely cause, open a GitHub issue with findings, and raise a PR if a clear fix is identified. |
| **REQ-05a** | As an operator, I want repeated firings of the same alert to be deduplicated against existing GitHub issues so a long-running alert produces one tracked issue, not one per run. | P0 | Before acting, the source checks for an open Labro-created issue fingerprinting the same alert (matched via a per-rule label, e.g. `ai-alert:<rule-uid>`, written when the issue is opened). If a matching open issue exists, the source returns no task and the run logs `skipped: already tracking <issue#>`. GitHub issue state is the single source of truth for dedup — Labro does not write back to Grafana in v1. When the alert clears, Labro posts an "alert cleared" comment on the issue but leaves it open for the operator to close, so the close reason (REQ-22) remains a clean success signal. **Accepted risk:** if the agent consistently fails before creating the tracking issue (e.g. auth failure, bad prompt), the alert will be retried every run indefinitely. Failure rate in the daily digest (REQ-21) surfaces this pattern. |
| **REQ-06** | As an operator, I want a `gh-delegated` task source that finds GitHub issues/PRs eligible for AI work via: (1) explicit labels (configurable list, e.g. `ai-analysis`, `ai-dev`, `ai-review`), and (2) implicit eligibility rules (configurable, e.g. "any open PR from `dependabot[bot]`"). | P0 | Config accepts a label list and an actor/origin allowlist; source returns all matching open items ranked by age or label precedence — the picker takes the top item only (one task per run). Each label entry may declare its own permitted action override — e.g. `ai-dev` items get `open-pr` while `ai-review` items get `comment` only. This allows the operator to grant write access for development tasks without over-permitting review tasks. |
| **REQ-07** | As an operator, I want a `proactive-improvement` task source with a configurable target list and selection strategy so I control the scope of proactive work. | P1 | Config declares: (1) an ordered list of improvement targets, (2) a selection strategy (`agent-chooses` or `harness-random`), (3) a maximum open issue cap (per-project, independently configurable). If the number of open GitHub issues labelled `ai-proactive-suggestion` meets or exceeds the configured cap, the source returns no task and the harness skips agent invocation for this source. The cap counts open issues only — not open PRs; a backlog of unmerged proactive PRs is outside Labro's scope to throttle. Stale issues accumulate against the cap indefinitely; the operator clears them via normal GitHub workflow. |
| **REQ-08** | As an operator, I want a configurable output mode for proactive improvement results so suggestions land where I want them. | P1 | Config selects output mode; v1 supports `gh-issue` (opens a GitHub issue) and `open-pr` (raises a PR where a concrete change is warranted). Whether `open-pr` is available is gated by the source's permitted actions; the agent raises a PR when it has a concrete, justified change and otherwise falls back to a `gh-issue`. Email output is out of scope for v1 — proactive suggestions are visible via the daily digest (REQ-21). |

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
| `surprise-me` | Agent selects its own focus area with no constraint — open-ended exploration. Default permitted action in example config is `comment`/`gh-issue`; operator must explicitly grant `open-pr` to enable PR output. |

**Example priority list (Ross's first project):**
1. `grafana-alerts` — firing production alert → Claude Sonnet (needs reasoning and context)
2. `gh-delegated` — issues/PRs labelled `ai-analysis`, `ai-dev`, or `ai-review`; OR opened by `dependabot[bot]` → Claude Code (cheaper model for Dependabot, capable model for labelled issues)
3. `proactive-improvement` — agent proposes something useful when no urgent work exists (output: GitHub issue or PR where a concrete change is warranted) → Claude Code + cheaper model

**Example permitted actions (Ross's first project):**

| Task Source | Permitted Actions |
| :--- | :--- |
| `grafana-alerts` | `comment`, `open-pr` — triage and surface findings; PR only if clear fix identified |
| `gh-delegated` | `comment` — Labro agents do not `approve` PRs in v1 (see note below) |
| `proactive-improvement` | `comment`, `open-pr` — suggest by default; raise a PR where a concrete, justified change exists |

> **v1 policy — no autonomous PR approval.** Labro agents may not `approve` PRs in v1/MVP, per Design Principle #5 (suggest over act). The `approve` action category still exists in the config schema (REQ-12) so it can be granted later once trust is established, but it is not enabled for any task source in v1.

| ID | User Story | Priority | Acceptance Criteria |
| :--- | :--- | :--- | :--- |
| **REQ-09** | As an operator, I want to configure which model to use at the task-source level (with a project-level default fallback) so I can route simpler tasks to cheaper models and reserve more capable models for complex work. | P0 | Each task source in config optionally declares a model; if absent, the project-level default applies. The v1 agent is Claude Code CLI; the model parameter is passed through to the Claude Code invocation. |
| **REQ-10** | As an operator, I want the selected agent invoked with the constructed task prompt and its output captured so the harness can log outcomes regardless of which agent ran. | P0 | Harness abstracts agent invocation; stdout/stderr captured for all supported agents. |
| **REQ-11** | As an operator, I want the agent to have access to `gh` CLI commands so it can act on GitHub (comment, open PRs, push fixes). | P0 | The real `gh` CLI is available to the agent in the container. Authenticated via `GH_TOKEN`. |
| **REQ-12** | As an operator, I want to define a action permissions in config at both the project level and the task-source level so I control the blast radius of autonomous runs with fine-grained precision. | P0 | Config declares which GitHub write action categories are enabled (e.g. `comment`, `approve`, `open-pr`, `merge`, `push`) at the project level as a default; each task source may optionally override with its own action permissions. Permitted actions govern side-effectful GitHub operations only — read operations, web searches, MCP tool calls, and local file operations are always unrestricted. Enforcement is via the prompt only (v1) — the action permissions is communicated to the agent as an instruction. A `gh` wrapper for hard runtime enforcement is a candidate for v1.1 if prompt-only proves insufficient. |
| **REQ-13** | As an operator, I want the agent to run in a sandboxed environment so mistakes don't affect my main dev environment. | P1 | Agent runs inside Docker; file system access scoped to cloned repo. |

| ID | User Story | Priority | Acceptance Criteria |
| :--- | :--- | :--- | :--- |
| **REQ-20** | As an operator, I want the harness to transition GitHub labels as a deterministic post-run step so task state is always consistent and items are not re-selected on future runs. | P0 | Applies to `gh-delegated` tasks (GitHub issues/PRs that carry Labro labels). On successful completion: harness applies the configured done label (e.g. `ai-dev-done`) and removes the source label. On failure: harness applies `ai-failed` and posts a comment with the agent's self-reported failure reason; item is skipped on all subsequent runs until the operator manually clears the label. Label transitions are configured per task source. Does not apply to `grafana-alerts` — those tasks have no GitHub item to label; dedup for alerts is handled via REQ-05a. |
| **REQ-21** | As an operator, I want Labro to send a single daily digest across all configured projects so I can assess system health without manually inspecting logs. | P1 | Digest fires once per day on a fixed schedule (independent of any project's cron). Delivered via Slack incoming webhook (`SLACK_WEBHOOK_URL` env var). Content covers all projects in a single summary: runs fired, tasks selected per source, tasks skipped (and why), token spend, and any failure labels applied. Digest is a health and cost signal — not a duplicate of ambient GitHub/Slack notifications generated by agent actions. |

| ID | User Story | Priority | Acceptance Criteria |
| :--- | :--- | :--- | :--- |
| **REQ-14** | As an operator, I want each run logged with: task type, task description, agent and model used, start/end time, token usage, rounds used, and agent completion reported outcome. | P0 | Structured log written per run. |
| **REQ-15** | As an operator, I want to know whether the agent believed it succeeded and what actions it took (e.g. "opened PR #42", "pushed commit abc123"). | P0 | Agent output parsed for action summary; stored alongside run log. |
| **REQ-16** | As an operator, I want a simple way to review recent runs so I can spot failures or bad behaviour quickly. | P1 | `labro review` prints a table of recent execution records from SQLite (default: last 20 runs) with columns for timestamp, project, task source, outcome, turns used, cost, and task description. Supports `--limit`, `--project`, and `--outcome` filters. |
| **REQ-16a** | As an operator, I want to inspect what Labro *would* do before it touches GitHub so I can validate my configuration without spending tokens. | P1 | `labro run <project> --dry-run` runs task selection and prompt construction then prints the resolved task, effective agent config, and full prompt text to stdout. It does not acquire a lock, prepare the repo, invoke the agent, write execution records, or apply label transitions — zero side effects. `labro check` performs a read-only pre-flight validation: checks all required env vars are set, verifies the GitHub token has the required scopes, and confirms all required labels exist in each configured repo. Reports pass/fail per check with a descriptive error for each failure. Both commands are safe to run at any time. |
| **REQ-17** | As an operator, I want token and time costs aggregated by agent and model so I can understand and control spend. | P1 | Daily/weekly summary queryable from logs; broken down by agent/model. |
| **REQ-22** | As an operator, I want Labro to capture *outcome* signals for past tasks from passive GitHub state so I can judge real usefulness without manual bookkeeping. | P0 | The daily digest job (not the run loop) owns outcome signal collection. It queries the `items_touched` SQLite table — populated by the harness at run time — to find all GitHub items Labro has acted on, then reads their current state from GitHub (PR merged vs. closed-unmerged, issue close reason `completed` vs. `not planned`, follow-up commits before merge) and writes outcome signals back to SQLite against the originating `run_id`. The run loop is only responsible for writing accurate `items_touched` records; the digest job does all GitHub state lookups. |
| **REQ-23** | As an operator, I want to express explicit satisfaction with a single click so I can correct or confirm Labro's self-reported success cheaply. | P1 | Labro reads 👍/👎 reactions on its own issue/PR comments via the GitHub API and records them as a satisfaction signal against the originating run. Items with no reaction are excluded from the satisfaction ratio — not counted as negative. The daily digest (REQ-21) includes an "awaiting your verdict" section listing recently-acted items with direct links, and surfaces both the satisfaction ratio and the reaction count so the operator can judge sample size. |

**Success signal model**

Labro distinguishes three signals; only the first is available at run time, so the digest reports satisfaction for *previous* runs, never the current one.

| Signal | Type | Source | Operator effort | Interpretation |
| :--- | :--- | :--- | :--- | :--- |
| Agent completion report | leading, subjective | agent output (REQ-15) | none | "the agent believed it succeeded" — a hint, not ground truth |
| PR merged / issue closed | lagging, objective | native GitHub state (REQ-22) | zero (normal review) | the work survived contact with the operator |
| Issue closed `not planned` | lagging, objective | native GitHub state (REQ-22) | one click | the task was noise |
| Follow-up commits before merge | lagging, objective | native GitHub state (REQ-22) | zero | needed correction → feeds the **human override rate** supporting metric |
| 👍 / 👎 reaction | lagging, subjective | GitHub reactions API (REQ-23) | one click | explicit operator sentiment |

Labels remain reserved for Labro's own lifecycle state (REQ-20); human sentiment is captured via reactions and close-reason, not labels, to keep the two families from colliding in the UI.

| ID | User Story | Priority | Acceptance Criteria |
| :--- | :--- | :--- | :--- |
| **REQ-18** | As an operator, I want to configure which GitHub repos Labro monitors, with per-project cron schedules, priority lists, permitted actions, and a default agent/model that individual task sources can override. | P0 | Config file supports multiple projects; each project declares its own cron schedule, a default agent/model, default permitted actions, an `enabled` flag (default `true`), and an ordered task source list where each source may optionally override the agent/model and permitted actions. A global `LABRO_DISABLED` env var or lockfile pauses all projects regardless of per-project config. |
| **REQ-19** | As an operator, I want to be able to add a new project to Labro with minimal effort. | P1 | Adding a repo requires only config changes, no code changes. |

*(Priority Scale: P0 = Critical/Launch blocking, P1 = Important/Should have, P2 = Nice to have)*

---

## User Experience & Interface

Labro is a headless, operator-facing tool. There is no end-user UI.

* **Operator interface:** Config file + structured log files + daily digest.
* **Operator touchpoints:** Two distinct channels surface Labro's activity:
  * **Daily digest (async, pull):** Slack summary of runs, task selections, skips, costs, and failures. This is the primary "is this working?" signal — health and cost visibility, not action replay.
  * **Ambient notifications (real-time, push):** Agent actions on GitHub and Slack generate their own notifications (GitHub mentions, issue assignments, PR activity, Slack namechecks). These are not mediated by Labro; they surface through the operator's normal channels.
* **Trust expansion:** Permitted actions are expanded manually by the operator, informed by observability data. Labro does not prompt for permission upgrades.
* **Key operator flow:**
  1. Operator adds a repo to config with a cron schedule, priority list, and per-source permitted actions
  2. Operator runs `labro check` (pre-flight: validates config, env vars, GitHub token scopes, and required labels) and `labro run <project> --dry-run` (prints which task would be selected and the exact prompt the agent would receive — zero side effects, no tokens spent)
  3. Cron triggers task picker for that project
  4. Task picker evaluates priority list and selects highest-priority task
  5. Agent is invoked with constructed prompt (scoped to effective permitted actions)
  6. Agent executes (gh commands, git operations)
  7. Harness performs label transitions (success → done label; failure → `ai-failed` + comment)
  8. Run result and action summary logged
  9. Operator receives daily digest summarising health and spend

---

## Technical & Constraints

* **Runtime:** Docker container; Python 3.12+.
* **Supported agents (v1):** Claude Code CLI (`claude -p`) only. Model is configurable per project and optionally per task source. The agent abstraction layer in the harness is designed to support additional agents in future versions without code changes to the core.
* **GitHub integration:** The real `gh` CLI is available to the agent in the container, authenticated via `GH_TOKEN`. Permitted action enforcement in v1 is prompt-only — the action permissions is communicated to the agent as an instruction; there is no runtime wrapper script blocking disallowed calls. A `gh` wrapper for hard enforcement is a candidate for a future version if prompt-only proves insufficient (see REQ-12).
* **Scheduling:** System cron inside the Docker container, configurable frequency per project (default: hourly). The Docker entrypoint reads `labro.toml` at container start and writes the crontab — adding a project requires only a config change and a container restart. Runs can also be triggered on demand via `labro run <project>`. Concurrency is controlled via a `project_locks` SQLite table: a run acquires a lock on start and releases it on completion. If a lock is already held when the next tick fires, the tick exits immediately and logs `skipped: run in progress` — no queuing, no parallel execution. Stale locks (from crashes) are cleared automatically if older than the configured run timeout. `labro list-locks` and `labro unlock <project>` allow manual inspection and recovery. A high skip rate in the digest signals the cron interval needs widening or `--max-turns` tightening.
* **Persistence:** Structured execution records stored in SQLite (`labro.db`); bind-mounted from host so data survives container restarts. No external database service required.
* **Security/Privacy:** GitHub token scoped to minimum required permissions. No secrets stored in logs. Agent output sanitised before logging.
* **Performance:** Each run should complete within a configurable timeout and/or maximum turn count to prevent runaway agent sessions consuming excessive tokens. Where the agent supports it (e.g. Claude Code CLI's `--max-turns`), turn limiting is preferred as it bounds cost more precisely than time alone.
* **Spend control (v1 decision):** Per-run bounds (timeout, `--max-turns`) cap a single run, but v1 deliberately has **no aggregate budget cap** that halts runs across a day/week. Spend is observe-only — captured and surfaced in logs and the daily digest (REQ-17, REQ-21) — on the basis that per-run caps plus daily visibility are sufficient for a single operator's projects. An aggregate spend ceiling is a candidate for a later version if observed cost warrants it.
* **Dependencies:** Claude Code CLI (`claude`) must be available and authenticated in the container.
* **Monitoring integration (v1):** Grafana alerts via Grafana HTTP API. Other alert sources (PagerDuty, Uptime Robot, etc.) are out of scope for v1 but the task source module interface should not preclude them.

---

## Open Questions / Risks

No open questions. All decisions resolved and reflected in the requirements above.

