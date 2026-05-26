# Roadmap: Labro Delivery Milestones

* **Status:** Draft
* **Author:** Ross Arnold
* **Date:** 2026-05-26
* **Architecture:** [docs/ARCHITECTURE.md](ARCHITECTURE.md)

Each milestone produces a runnable, testable increment. Every source file and data model is listed in exactly one milestone under "Completed here" — if a component is extended in a later milestone, that extension is called out explicitly.

---

## M1 — `labro run --dry-run`

**Goal:** operator can inspect "what would Labro do?" against a real GitHub repo with a minimal config covering one label rule. No tokens spent, no side effects, no SQLite writes.

**Completed here:**

| Component | Notes |
| :--- | :--- |
| Docker image | Python 3.12, `gh` CLI, `claude` CLI pre-installed |
| `config/` — config loader + Pydantic schema | Full schema validated; only `gh-delegated` label_rules exercised in M1 |
| `task_sources/base.py` | `TaskSource` abstract base class |
| `task_sources/gh_delegated.py` | `label_rules` only — actor_rules added in M2 |
| `picker.py` | Complete priority-stack evaluator; iterates sources, returns first `Task | None`; no changes required in later milestones when new sources are registered |
| `prompt_builder.py` | Complete four-section prompt constructor |
| `agents/base.py` | `Agent` abstract base class |
| `Task` data model | Full schema; `item_type`/`item_number`/`item_url` populated for `gh-delegated` items |
| `AgentConfig` data model | Fully defined; used by dry-run output |
| `cli.py` — `labro run <project> --dry-run` | Prints resolved task + agent config + full prompt to stdout; exits cleanly |

**Explicitly out of scope:**
- `AgentResult`, `runner.py`, `agents/claude_code.py` — no agent invocation
- `store.py`, `logger.py` — no SQLite
- `repo.py` — no repo preparation
- `post_run.py` — no label transitions
- Actor rules in `gh-delegated`

---

## M2 — Full run loop

**Goal:** `labro run <project>` does real work end-to-end on a single `gh-delegated` project. Agent is invoked, labels are transitioned, run record is written to SQLite.

**Completed here:**

| Component | Notes |
| :--- | :--- |
| `task_sources/gh_delegated.py` — actor_rules | Completes `gh_delegated.py`; no further changes required |
| `AgentResult` + `ItemRef` data models | Fully defined |
| `agents/claude_code.py` | Complete Claude Code CLI agent implementation |
| `runner.py` | Subprocess invocation; stdin prompt delivery; JSON parse; timeout handling |
| `repo.py` | Clone/pull to default branch; dirty-repo detection; `git reset --hard` + `git clean -fd` recovery |
| `store.py` | SQLite WAL-mode setup; `runs`, `project_locks`, `items_touched` tables and indexes. `digests` table added in M7 |
| `logger.py` | Write run records to SQLite; release lock unconditionally in `finally` block |
| `post_run.py` | Label transitions for both `gh-delegated` rule types: label_rules (remove source label on success; keep on failure) and actor_rules (no source label to remove). Both paths apply done_label on success, `ai-failed` on failure, `ai-contributed` in all cases. Failure comment posted on both rule types. Extended in M5 (`ai-alert:<rule-uid>`) and M6 (`ai-proactive-suggestion` enforcement) |
| `cli.py` — `labro run <project>` (non-dry-run) | Full run; `LABRO_DISABLED` lockfile check added here |

---

## M3 — Operator CLI

**Goal:** operator tooling for bootstrapping, health-checking, and reviewing run history is complete. The system is fully operable without reading source code.

**Completed here:**

| Component | Notes |
| :--- | :--- |
| `cli.py` — `labro init` | Idempotent GitHub label creation across all configured repos |
| `cli.py` — `labro check` | Pre-flight: config validity, env vars, GitHub token scope, label existence; no writes |
| `cli.py` — `labro review` | Tabular run history from SQLite; `--limit`, `--project`, `--outcome` flags |
| `cli.py` — `labro list-locks` | Show held project locks with age |
| `cli.py` — `labro unlock <project>` | Manual stale-lock release |

---

## M4 — Autonomous scheduler

**Goal:** container runs autonomously on a cron schedule. Operator edits `labro.toml` and restarts the container — no other change required to add or modify a project.

**Completed here:**

| Component | Notes |
| :--- | :--- |
| `entrypoint.sh` | Exports env to `/etc/labro-env`; generates `/etc/cron.d/labro` from `labro.toml`; execs `crond -f` |
| Crontab generation | Per-project entries + digest entry; disabled projects omitted; format documented in ARCHITECTURE.md §7 |
| Docker bind-mount layout | `/config/`, `/data/`, `/repos/` verified and documented |

---

## M5 — `grafana-alerts` source

**Goal:** firing Grafana alerts trigger agent investigation runs automatically; dedup prevents duplicate tracking issues.

**Completed here:**

| Component | Notes |
| :--- | :--- |
| `task_sources/grafana_alerts.py` | Alert fetch; severity filter; dedup via open issue carrying `ai-alert:<rule-uid>`; alert-cleared comment path |
| `post_run.py` — `ai-alert:<rule-uid>` application | Extends M2 post-run logic; applies label from `task.grafana_rule_uid` on first-alert success |

---

## M6 — `proactive-improvement` source

**Goal:** Labro autonomously proposes improvements to configured projects when no delegated work is queued.

**Completed here:**

| Component | Notes |
| :--- | :--- |
| `task_sources/proactive_improvement.py` | Open-suggestion cap check; target selection (`agent-chooses` + `harness-random` strategies) |
| `post_run.py` — `ai-proactive-suggestion` enforcement | Extends M5 post-run logic; first `items_created` entry only; logs warning and applies `ai-contributed` only to extras |

---

## M7 — Daily digest

**Goal:** operator receives a daily Slack summary covering runs, costs, and outcome signals, without needing to check GitHub or query SQLite directly.

**Completed here:**

| Component | Notes |
| :--- | :--- |
| `store.py` — `digests` table | Scheduling anchor and failure tracking; extends M2 store |
| `digest.py` | All four phases: outcome signal collection, run stats aggregation, Slack message assembly, HTTP POST delivery |
| `cli.py` — `labro digest [--dry-run]` | `--dry-run` skips Phase 1 (no `signals_collected_at` writes) and Phase 4 (no Slack POST); no `digests` row written |
| `items_touched` outcome signal columns populated | Columns exist in schema from M2; collection logic (`outcome_state`, `follow_up_commits`, `thumbs_up`, `thumbs_down`, `signals_collected_at`) implemented here |
