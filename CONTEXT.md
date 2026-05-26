---
name: labro-context
description: Domain glossary for Labro — autonomous agent harness
metadata:
  type: reference
---

# Labro — Domain Glossary

## Core Concepts

**Harness**
The Labro process itself. Deterministic, auditable orchestration layer: selects a task, constructs a prompt, invokes an agent, records the result. Does not attempt reasoning — the agent is smart; the harness is not.

**Operator**
The person who configures and runs Labro. In v1, this is a single person (Ross). Responsible for setting cron schedules, priority stacks, and permitted action sets. Expands agent permissions manually based on observability data.

**Project**
A single GitHub repository configured in `labro.toml`. Each project has its own cron schedule, priority stack, default agent/model, and permitted action set.

**Task**
A single unit of work selected by the Picker for a given run. Produced by exactly one Task Source. A run produces at most one task; if no task is found, the run is logged as `skipped`.

**Task Source**
A pluggable module that knows how to find work for a given project. Built-in sources: `grafana-alerts`, `gh-delegated`, `proactive-improvement`. Each source implements `is_available()` and `fetch_task()`.

**Priority Stack**
An ordered list of Task Sources declared per project in config. The Picker evaluates sources top-to-bottom and takes the first task returned. Earlier entries represent higher-priority work.

**Picker**
The component that iterates the priority stack and selects one task per run.

**Project Lock**
A row in the SQLite `project_locks` table (`project`, `locked_at`) held for the duration of a run. Prevents concurrent runs for the same project. Released on run completion; stale locks (from crashes) are overwritten if older than the configured run timeout. Inspectable via `labro list-locks`; manually clearable via `labro unlock <project>`.

**Repo Preparation**
A pre-agent step (`repo.py`) that ensures the working copy is on the project's default branch (read from GitHub) and clean before the agent is invoked. If the repo is absent, it is cloned. If it is present but dirty (uncommitted changes or untracked files from a previous run), the harness logs a warning, resets hard, and surfaces the anomaly in the daily digest.

**Permitted Action Set**
The set of action categories (e.g. `comment`, `open-pr`, `merge`) an agent is allowed to perform in a given run. Declared at project level; overridable per task source. Communicated to the agent via the prompt (v1); no runtime enforcement mechanism. See [[adr-003-prompt-only-enforcement]].

**Agent**
An AI coding CLI (Claude Code CLI or Aider in v1) invoked as a subprocess by the harness. Treated as a black box; interacts with GitHub via the `gh` wrapper.

**Run**
A single execution cycle for one project: task selected → prompt constructed → agent invoked → post-run actions → result logged.

**Run Record**
A structured record written to SQLite per run. Fields include: `run_id`, `project`, `task_source`, `task_description`, `agent`, `model`, `started_at`, `ended_at`, `duration_s`, `token_usage`, `turns_used`, `outcome`, `actions_taken`, `failure_reason`.

**Outcome**
The result of a run: `success`, `failure`, or `skipped`.

**Agent Self-Report**
The agent's own structured assessment of whether it succeeded and what actions it took. A leading, subjective signal — not ground truth.

**Daily Digest**
A scheduled summary (email or Slack) covering all projects: runs fired, tasks selected per source, skips, token spend, failures, and outcome signals for prior runs. The primary "is this working?" signal for the operator. Also owns outcome signal collection: queries the `items_touched` table, reads current GitHub state for each item, and writes outcome signals back to SQLite before generating the report.

**Permitted Actions**
See *Permitted Action Set*.

**Label Transition**
A deterministic post-run step (not agent-driven) that applies or removes GitHub labels to reflect task state. On success: applies done label, removes source label, applies `ai-contributed`. On failure: applies `ai-failed`, posts failure comment, applies `ai-contributed`.

**Marker Label (`ai-contributed`)**
A universal GitHub label applied to every PR or issue Labro creates or acts on, as part of the post-run step. Serves as the query surface for outcome tracking (REQ-22) and satisfaction tracking (REQ-23). Does not embed the harness name — labels use the `ai-` prefix only, so the convention remains meaningful if other AI tooling is introduced. See [[github-as-state-store]].

**Deduplication (alert)**
Before acting on a Grafana alert, `grafana-alerts` checks for an open Labro-created GitHub issue fingerprinted with `ai-alert:<rule-uid>`. If one exists, the run is logged as `skipped: already tracking <issue#>`. GitHub issue state is the single source of truth for dedup.

**Outcome Signal**
A lagging indicator of real usefulness read from passive GitHub state: PR merged vs. closed-unmerged, issue close reason (`completed` vs. `not planned`), follow-up commits before merge, and 👍/👎 reactions on Labro comments. Collected by the daily digest job (not the run loop), written back to SQLite against the originating `run_id`.

**`items_touched` Table**
A SQLite table populated by the harness per run, recording every GitHub item Labro created or acted on: `(run_id, repo, item_type, item_number)`. For `gh-delegated` tasks, written at task-selection time. For agent-created items, written post-run from the `items_created` field of the agent's structured output. The daily digest job queries this table to collect outcome signals.
