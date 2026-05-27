# Case for Self-Build: Labro

* **Status:** Reference
* **Author:** Ross Arnold (with Claude Sonnet 4.6 analysis, May 2026)
* **PRD:** [docs/PRD.md](PRD.md)

---

## Purpose

This document records the competitive landscape analysis conducted before starting implementation, and the reasoning behind the decision to build Labro rather than use or extend an existing free tool. It is intended as a durable reference — if a future version of this conversation ever revisits that decision, this is where to start.

---

## Full Competitive Landscape

The tools surveyed fall into five clusters. The five originally listed in the PRD are included here for completeness.

### Cluster 1 — PR-Review Bots (reactive, event-driven)

| Tool | Licence | Self-hosted? | Description | Gap vs. Labro |
|---|---|---|---|---|
| [PR-Agent](https://github.com/The-PR-Agent/pr-agent) (formerly Qodo Merge) | Apache 2.0 (donated to community 2025) | ✅ Docker | Triggered by PR events; reviews, summarises, suggests. Supports GitHub, GitLab, Bitbucket, Azure DevOps. | No task selection layer, no scheduling, no proactive work, no alert integration, no permission envelopes, no outcome tracking. |
| [Sweep AI](https://docs.sweep.dev/) | Apache 2.0 (backend was always closed) | ⚠️ Effectively abandoned as self-hosted harness; pivoted to JetBrains plugin | GitHub issue → autonomous PR. Labels an issue, Sweep creates a branch, commits changes, opens a PR. | No scheduling, no priority queue, narrow issue→PR only; maintenance status uncertain. |
| [GitHub Agentic Workflows](https://github.blog/changelog/2026-02-13-github-agentic-workflows-are-now-in-technical-preview/) | Open (GitHub Actions) | ✅ (GitHub-native) | Event-driven AI within GitHub Actions. Handles issue triage, PR review, CI failure analysis. | Tightly GitHub-coupled; each workflow is independent; no cross-repo priority logic; no persistent observability. |

### Cluster 2 — General Autonomous Coding Agents (no scheduling layer)

| Tool | Licence | Self-hosted? | Description | Gap vs. Labro |
|---|---|---|---|---|
| [OpenHands](https://www.openhands.dev/) (formerly OpenDevin) | MIT | ✅ | Full-stack agent platform; web UI; ~77% SWE-Bench Verified (Opus 4.5). Two-tier architecture: long-lived app container + per-task sandbox container spawned via Docker socket. | No task selection or priority layer; no Grafana integration; no per-source permission envelopes; heavyweight deployment model (multi-service, port 3000 web UI). RFC for scheduled automations exists ([#13275](https://github.com/OpenHands/OpenHands/issues/13275)) but unshipped. |
| [SWE-agent](https://swe-agent.com/latest/) (Princeton) | MIT | ✅ | Research-focused; custom Agent-Computer Interface (ACI); designed for GitHub issue → automated fix. Strong benchmark performance. | Research tool, not a harness; no scheduling, no task prioritisation, no observability, no permission model. |
| [Cline](https://cline.bot/) | MIT | ✅ | Open-source AI coding agent (VS Code extension + CLI). Explicitly supports running in cron jobs and CI pipelines. | Designed for interactive use; no task-selection layer, observability, or project config model out of the box. |
| [Mentat](https://aiagentstore.ai/ai-agent/mentat) | MIT | ✅ | Multi-file editing with project-wide context awareness. | Low activity, interactive focus, no scheduling or task selection. |
| [Sandcastle](https://github.com/mattpocock/sandcastle) | MIT | ✅ | TypeScript *library* for orchestrating AI coding agents in sandboxed environments. Multi-provider sandboxes (Docker, Podman, Vercel Firecracker), configurable branch strategies (head / merge-to-head / named branch), structured JSON output via Zod, session resume. Supports Claude Code and Codex. | SDK, not an application — `sandcastle.run()` is a library call, not a schedulable process. No task selection, priority queue, or scheduling. No GitHub-native integrations (task sources, label transitions). No audit trail or SQLite persistence. No permission envelopes. Sandboxing is filesystem-only (bind-mounted worktree); no network isolation. TypeScript-only; adds a Node runtime dependency if embedded in a Python project. **Complementary rather than competing**: could serve as Labro's sandbox/agent-invocation layer once the agent requires hard filesystem isolation (M3+). |

### Cluster 3 — Cron/Scheduled Agent Platforms (general-purpose, not project-maintenance)

| Tool | Licence | Self-hosted? | Description | Gap vs. Labro |
|---|---|---|---|---|
| [OpenClaw](https://docs.openclaw.ai/automation/cron-jobs) | OSS | ✅ | General personal AI assistant with cron scheduling; 50+ messaging platform integrations; GitHub PR review is one documented use case. Cron jobs run in isolated sessions with their own context and model. | Chat-agent architecture, not a software maintenance harness; no project-aware priority lists; no multi-source task selection (grafana + gh-delegated + proactive); no outcome tracking; no permission envelopes. |
| [Autobot](https://veelenga.github.io/how-agent-loop-and-cron-work-together-inside-autobot/) | OSS | ✅ | Agent framework with built-in cron scheduling; routes scheduled tasks through the same message bus as interactive agent sessions. | General agent loop; no software-project-specific integrations; no GitHub/Grafana sources; no observability. |
| [CronBox](https://www.producthunt.com/products/cronbox-2) | Closed | ❌ Cloud only | Cloud-hosted product specifically for scheduling AI agents on a cron basis. | Not self-hosted; no software-project-specific integrations. |

### Cluster 4 — Issue Triage Specialists (narrow scope)

| Tool | Licence | Self-hosted? | Description | Gap vs. Labro |
|---|---|---|---|---|
| [trIAge](https://github.com/trIAgelab/trIAge) | OSS | ✅ | LLM-powered issue triage, labelling, and user support for open-source communities. Can be deployed as a GitHub App. Access to project context (code, docs, guidelines). | Narrow scope: triage only, no code changes, no PRs, no alert integration, no proactive improvement; aimed at open-source maintainers not solo devs. |
| [GitHub native AI triage](https://docs.github.com/en/issues/tracking-your-work-with-issues/administering-issues/triaging-an-issue-with-ai) | Closed | ❌ GitHub.com only | GitHub's built-in issue intake AI; analyses incoming issues and provides triage suggestions. | Platform-locked; no code changes; no scheduling; no custom priority logic. |

### Cluster 5 — Fleet-Scale / Enterprise Orchestration (overengineered for the use case)

| Tool | Licence | Self-hosted? | Description | Gap vs. Labro |
|---|---|---|---|---|
| [SWE-AF / AgentField](https://github.com/Agent-Field/SWE-AF) | OSS | ✅ | Multi-agent fleet: planner → parallel coders → reviewer → merger → verifier. Checkpointed execution, thousands of concurrent agent invocations. | Enterprise fleet architecture; massive operational overhead; no lightweight personal-project orientation. |
| [AWS remote-swe-agents](https://github.com/aws-samples/remote-swe-agents) | Sample code | ❌ AWS-coupled | Cloud-based autonomous SWE agents on AWS infrastructure. | AWS-coupled; sample code only; no task selection, no personal project orientation. |

---

## Build vs. Compose: The Realistic Paths

The question is not whether to build an agent — Claude Code CLI already exists and is excellent. The question is whether the **harness** (task selection, permission envelopes, observability, outcome tracking) can be assembled from existing tools instead of written from scratch.

### Path A: PR-Agent + custom cron wrapper

PR-Agent is the closest free tool to parts of what Labro does. Running it on a schedule with a cron wrapper gives: PR review when a PR is opened. Still needed from scratch: the priority list and task picker, Grafana alert integration, proactive improvement source, per-source permission envelopes, outcome tracking (reaction signals, merge rate, close reasons), daily digest, SQLite persistence, label lifecycle management, alert deduplication.

**Verdict:** You'd be writing Labro anyway, with PR-Agent handling one narrow task type. PR-Agent's architecture is event-driven (webhook on PR open) rather than pull-based, so it doesn't naturally compose into a cron-based priority queue.

### Path B: OpenHands CLI invoked from cron

OpenHands has a headless CLI mode and a [planned RFC](https://github.com/OpenHands/OpenHands/issues/13275) for scheduled/event-driven automations. But: it's a heavyweight multi-service deployment (app container + per-task sandbox containers via Docker socket); the RFC is unshipped; it has no concept of a configurable priority list across multiple source types; no permission envelopes; no structured outcome tracking.

**Verdict:** The harness layer doesn't exist in OpenHands. You'd write it anyway, and then choose between invoking Claude Code CLI (one subprocess) or OpenHands-as-agent (two-tier containers, Docker socket, port 3000) at the end. Claude Code CLI wins on simplicity for the agent role.

### Path C: OpenClaw

OpenClaw has the right deployment model (lightweight, self-hosted, cron-aware) but the wrong architecture (chat-agent with scheduled prompts, not a software maintenance harness). There is no project-specific priority list, no multi-source evaluation, no outcome observability. Using it would mean writing a harness on top of a chat-agent abstraction, which adds friction rather than removing it.

**Verdict:** Interesting to watch, architecturally wrong for this use case.

### Path D: Fork/extend Sweep AI

Sweep originally had the closest conceptual match (label an issue → autonomous PR). But it is effectively unmaintained as a self-hosted harness (pivoted to JetBrains plugin). It only ever covered the issue→PR flow — never had scheduling, priority selection, Grafana integration, or observability.

**Verdict:** Dead end for self-hosted use.

---

## What Is Genuinely Unique to Labro

After surveying the full landscape, four things exist in Labro that have no free/open equivalent:

**1. Configurable priority-list task selection across heterogeneous sources.**
The picker that evaluates `grafana-alerts → gh-delegated → proactive-improvement` top-to-bottom, returning the first non-empty task, is architecturally novel. No existing tool has a multi-source priority queue for software maintenance work. This is the core value proposition.

**2. Per-project, per-task-source action permission envelopes.**
The idea that `grafana-alerts` can open PRs while `gh-delegated` can only comment, all expressed in TOML config, is not available in any free tool. PR-Agent has a coarser model; OpenHands has prompt-level permissions at best. The blast-radius control this provides is what makes unsupervised scheduled operation safe enough to run on real projects.

**3. Passive outcome signal collection attributed to originating runs.**
The success signal model — PR merge rate, issue close reason, follow-up commits, 👍/👎 reactions, all collected passively from GitHub state and written back to SQLite against the originating `run_id` — is not available in any free tool. This is what distinguishes autonomous work that *compounds in value* (you can see what's working and tune accordingly) from autonomous work you evaluate manually.

**4. Grafana alert integration as a first-class task source with deduplication.**
The loop of `firing alert → triage agent → GitHub issue with fingerprint → dedup on subsequent runs → alert-cleared comment` is entirely novel. No existing tool treats a Grafana alert as a schedulable task source for a software maintenance agent.

---

## Risks to This Assessment

Things most likely to change the calculus, in priority order:

| Risk | Likelihood | Impact | Watch signal |
|---|---|---|---|
| OpenHands ships scheduled/event-driven automations ([RFC #13275](https://github.com/OpenHands/OpenHands/issues/13275)) with a task-source plugin model | Medium | Medium — narrows Labro's differentiation but OpenHands remains heavyweight and won't have project-priority-list semantics | RFC activity; merged PRs against that issue |
| PR-Agent grows a cron-based scheduling layer | Low — its architecture is webhook/event-driven, not pull-based; would require significant rethink | Low — still no priority list, no Grafana, no outcome tracking | PR-Agent repo releases |
| OpenClaw adds a software-project-specific plugin with priority lists | Low | Medium — if it ships project-priority-list semantics with Grafana + GitHub in a lightweight chat-agent it becomes a real alternative | OpenClaw plugin marketplace |

---

## Verdict

**Build Labro.** The harness is the product, and the harness is genuinely new.

The agent (Claude Code CLI) is borrowed. Several tools cover fragments of the problem: PR-Agent for PR review, trIAge for issue triage, OpenClaw for scheduled agent prompts. But no free tool combines:

- configurable multi-source priority selection
- per-project, per-source permission envelopes
- passive outcome signal tracking attributed to run IDs
- Grafana-to-GitHub alert pipeline with deduplication

The build complexity is also bounded: a Python process manager, a TOML config loader, three task source modules, a SQLite schema, and a Slack webhook. There is no frontier ML research here — it is engineering, and modest engineering at that. The effort-to-differentiation ratio is favourable.

The one honest alternative worth considering: skip the task picker and use direct cron entries (one entry per task type per project), invoking Claude Code CLI with hardcoded priorities. That gets ~60% of Labro's value in ~20% of the code. But it sacrifices the priority-list semantics (one task per run, higher-priority sources gate lower ones), permission envelopes, and outcome tracking — which are exactly the things that make scheduled autonomous work safe and measurable. Not a worthwhile shortcut.
