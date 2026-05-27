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
| `pyproject.toml` | Project metadata; `[project.optional-dependencies] dev` block: ruff, mypy (strict), bandit, pytest, pytest-cov, pip-audit; tool config sections for ruff, mypy, bandit, pytest (70% coverage floor, `runner.py` and `agents/` excluded from floor) |
| `.pre-commit-config.yaml` | Full hook config: ruff + mypy + bandit + shellcheck + check-toml (pre-commit stages); pip-audit with once-per-day marker (pre-push stage) |
| `tests/` scaffold | `tests/test_config.py`, `tests/test_picker.py`, `tests/test_prompt_builder.py`; quality gate in place before any side-effectful code is written in M2 |
| Docker image | Python 3.12, `gh` CLI, `claude` CLI pre-installed; `gh` availability satisfies REQ-11. Container image is the sandbox envelope for REQ-13 — agent execution inside the container is completed in M2 |
| `config/` — config loader + Pydantic schema | Full schema validated; only `gh-delegated` label_rules exercised in M1 |
| `task_sources/base.py` | `TaskSource` abstract base class |
| `task_sources/gh_delegated.py` | `label_rules` only — actor_rules added in M2 |
| `picker.py` | Complete priority-stack evaluator; iterates sources, returns first `Task | None`; no changes required in later milestones when new sources are registered |
| `prompt_builder.py` | Complete four-section prompt constructor |
| `agents/base.py` | `Agent` abstract base class |
| `Task` data model | Full schema; `item_type`/`item_number`/`item_url` populated for `gh-delegated` items |
| `AgentConfig` data model | Fully defined; used by dry-run output |
| `cli.py` — `labro run <project> --dry-run` | Prints resolved task + agent config + full prompt to stdout; exits cleanly |
| `README.md` | Scaffold: project overview, prerequisites, installation, first-run (`labro init` + `labro check` + `labro run --dry-run`), pointer to `docs/`. Documentation entry point exists before side-effectful code ships |

**M1 validation gate — `claude -p` in Docker:**
Before writing any M2 code, validate that `claude -p --print "hello" --output-format json` works inside the target Docker image with only `ANTHROPIC_API_KEY` set (no interactive auth session). Run:
```bash
docker run --rm -e ANTHROPIC_API_KEY=<key> <image> \
  sh -c 'echo "hello" | claude -p --output-format json'
```
Confirm the response contains `type`, `is_error`, and `result` fields at the expected top level. If interactive auth is required, resolve the container auth strategy before proceeding — this is a day-one blocker for M2.

**Explicitly out of scope:**
- `AgentResult`, `runner.py`, `agents/claude_code.py` — no agent invocation
- `store.py`, `logger.py` — no SQLite
- `repo.py` — no repo preparation
- `post_run.py` — no label transitions
- Actor rules in `gh-delegated`

**Coverage floor at M1 completion:** 70% across `config/`, `picker.py`, `prompt_builder.py`, `task_sources/gh_delegated.py`. Floor rises 5 pp each milestone; see ARCHITECTURE.md §8 Testing & Static Analysis for full policy.

---

## M2 — Agent invocation and logging

**Goal:** `labro run <project>` invokes the agent and writes a structured execution record to SQLite. Label transitions are deferred to M3 — this milestone isolates the subprocess/JSON-parsing integration risk before building the state machine on top of it.

**Completed here:**

| Component | Notes |
| :--- | :--- |
| `task_sources/gh_delegated.py` — actor_rules | Completes `gh_delegated.py`; no further changes required |
| `AgentResult` + `ItemRef` data models | Fully defined |
| `agents/claude_code.py` | Complete Claude Code CLI agent implementation |
| `runner.py` | Subprocess invocation; stdin prompt delivery; JSON parse; timeout handling; validates `structured_output` shape and fails loudly if missing |
| `repo.py` | Clone/pull to default branch; dirty-repo detection; `git reset --hard` + `git clean -fd` recovery |
| `store.py` | SQLite WAL-mode setup; `runs`, `project_locks`, `items_touched` tables and indexes. `items_touched` written in M3; `digests` table added in M8 |
| `logger.py` | Write execution records to `runs` table; release lock unconditionally in `finally` block |
| `cli.py` — `labro run <project>` (non-dry-run) | Full run minus post_run label transitions; `LABRO_DISABLED` lockfile check added here |
| `daily_budget_usd` enforcement | After lock acquisition: query `SUM(total_cost_usd) FROM runs WHERE project = :project AND DATE(started_at) = today`; skip with `skipped: daily budget exceeded ($X.XX of $Y.YY used)` if over cap |
| `README.md` | Add full run loop section: required env vars (`GH_TOKEN`, `ANTHROPIC_API_KEY`), `LABRO_DISABLED` emergency pause, `daily_budget_usd` config option; update quickstart to cover a real invocation |

**Explicitly out of scope:**
- `post_run.py` — no label transitions; `items_touched` rows not yet written

**Coverage floor at M2 completion:** 75%

---

## M3 — Label transitions and full loop

**Goal:** complete the run loop with GitHub label transitions and `items_touched` tracking. The system now produces all side effects of a real run on a `gh-delegated` project.

**Completed here:**

| Component | Notes |
| :--- | :--- |
| `post_run.py` | Label transitions for both `gh-delegated` rule types: label_rules (remove source label on success; keep on failure) and actor_rules (no source label to remove). Both paths apply done_label on success, `ai-failed` on failure, `ai-contributed` in all cases. Failure comment posted on both rule types. Extended in M6 (`ai-alert:<rule-uid>`) and M7 (`ai-proactive-suggestion` enforcement) |
| `items_touched` writes | For `gh-delegated`: written at task-selection time (item already known). For other sources (M6, M7): written post-run from `items_created` in `AgentResult` |
| `cli.py` — add post_run call | Completes the run loop; `store.py` `items_touched` write wired in |
| `README.md` | Document label transitions, `items_touched`, retry workflow (remove `ai-failed` to re-enable) |

**Coverage floor at M3 completion:** 80%

---

## M4 — Operator CLI

**Goal:** operator tooling for bootstrapping, health-checking, and reviewing run history is complete. The system is fully operable without reading source code.

**Completed here:**

| Component | Notes |
| :--- | :--- |
| `cli.py` — `labro init` | Idempotent GitHub label creation across all configured repos; completing this command means a new project is fully onboarded with a config change + `labro init` only (REQ-19) |
| `cli.py` — `labro check` | Pre-flight: config validity, env vars, GitHub token scope, label existence; no writes |
| `cli.py` — `labro review` | Tabular run history from SQLite; `--limit`, `--project`, `--outcome` flags; token and time costs shown per run and aggregated by agent/model (REQ-17) |
| `cli.py` — `labro list-locks` | Show held project locks with age |
| `cli.py` — `labro unlock <project>` | Manual stale-lock release |
| `README.md` | Document all CLI subcommands (`init`, `check`, `review`, `list-locks`, `unlock`) with flags; add troubleshooting section covering common startup failures (missing labels, missing env vars, stale locks) |

---

## M5 — Autonomous scheduler

**Goal:** container runs autonomously on a cron schedule. Operator edits `labro.toml` and restarts the container — no other change required to add or modify a project.

**Deployment pattern:** Labro uses a two-repo layout — the labro repo is the engine (published as a Docker image); a separate private config repo holds `labro.toml`, GitHub Secrets, and the workflow YAML that drives scheduling. See ARCHITECTURE.md §7 "Two-repo deployment pattern" for the full design, example GitHub Actions workflow, and VPS alternative.

**Completed here:**

| Component | Notes |
| :--- | :--- |
| `entrypoint.sh` | Exports env to `/etc/labro-env`; generates `/etc/cron.d/labro` from `labro.toml`; execs `crond -f` |
| Crontab generation | Per-project entries + digest entry; disabled projects omitted; format documented in ARCHITECTURE.md §7 |
| Docker bind-mount layout | `/config/`, `/data/`, `/repos/` verified and documented |
| `README.md` | Add Docker deployment section: image build, bind-mount layout, container restart workflow for adding or modifying a project; reference to two-repo pattern and `LABRO_CONFIG` env var |

---

## M6 — `grafana-alerts` source

**Goal:** firing Grafana alerts trigger agent investigation runs automatically; dedup prevents duplicate tracking issues.

**Completed here:**

| Component | Notes |
| :--- | :--- |
| `task_sources/grafana_alerts.py` | Alert fetch; severity filter; dedup via open issue carrying `ai-alert:<rule-uid>`; alert-cleared comment path |
| `post_run.py` — `ai-alert:<rule-uid>` application | Extends M3 post-run logic; applies label from `task.grafana_rule_uid` on first-alert success |
| `README.md` | Document `grafana-alerts` config block (`min_severity`, `permitted_actions`) and `GRAFANA_TOKEN` env var |

---

## M7 — `proactive-improvement` source

**Goal:** Labro autonomously proposes improvements to configured projects when no delegated work is queued.

**Completed here:**

| Component | Notes |
| :--- | :--- |
| `task_sources/proactive_improvement.py` | Open-suggestion cap check; target selection (`agent-chooses` + `harness-random` strategies) |
| `post_run.py` — `ai-proactive-suggestion` enforcement | Extends M6 post-run logic; first `items_created` entry only; logs warning and applies `ai-contributed` only to extras |
| `README.md` | Document `proactive-improvement` config block (`selection_strategy`, `max_open_suggestions`, `targets`) |

---

## M8 — Daily digest

**Goal:** operator receives a daily Slack summary covering runs, costs, and outcome signals, without needing to check GitHub or query SQLite directly.

**Completed here:**

| Component | Notes |
| :--- | :--- |
| `store.py` — `digests` table | Scheduling anchor and failure tracking; extends M2 store |
| `digest.py` | All four phases: outcome signal collection, run stats aggregation, Slack message assembly, local file write + HTTP POST delivery |
| `cli.py` — `labro digest [--dry-run]` | `--dry-run` skips Phase 1 (no `signals_collected_at` writes) and Phase 4 (no file write, no Slack POST); no `digests` row written |
| `items_touched` outcome signal columns populated | Columns exist in schema from M2; collection logic (`outcome_state`, `follow_up_commits`, `thumbs_up`, `thumbs_down`, `signals_collected_at`) implemented here |
| `README.md` | Document digest setup: `[digest]` config block, `SLACK_WEBHOOK_URL` env var, local file fallback at `/data/digest-YYYY-MM-DD.txt`, `labro digest --dry-run` for testing before live delivery |

---

## Requirements Coverage

Maps every PRD requirement to the milestone where it is first completed. Requirements split across milestones list the primary milestone; extensions are noted.

| REQ | Description | Milestone | Notes |
| :--- | :--- | :--- | :--- |
| REQ-01 | Per-project cron schedules | M5 | `entrypoint.sh` generates crontab from `labro.toml` |
| REQ-02 | Deterministic task selector | M1 | `picker.py` complete; no changes in later milestones |
| REQ-03 | Priority list in config | M1 | Full schema; picker evaluates top-to-bottom |
| REQ-04 | Built-in task source modules | M1 | `TaskSource` ABC; `gh-delegated` first concrete source |
| REQ-05 | `grafana-alerts` task source | M6 | Alert fetch, severity filter |
| REQ-05a | Alert dedup via `ai-alert:<rule-uid>` | M6 | Open-issue check before acting; cleared-alert comment path |
| REQ-06 | `gh-delegated` task source | M1 + M2 | `label_rules` in M1; `actor_rules` completed in M2 |
| REQ-07 | `proactive-improvement` task source | M7 | Cap check, target selection strategies |
| REQ-08 | Configurable output mode for proactive work | M7 | `gh-issue` and `open-pr` modes |
| REQ-09 | Model config per task source + project default | M1 | `AgentConfig` defined; passed to agent from M2 |
| REQ-10 | Agent invoked; stdout/stderr captured | M2 | `runner.py` subprocess invocation |
| REQ-11 | `gh` CLI available to agent | M1 | Pre-installed in Docker image; agent can use it from M2 |
| REQ-12 | Permitted actions in config; prompt enforcement | M1 + M3 | Schema in M1; prompt delivery in M2; label-transition enforcement in M3 |
| REQ-13 | Agent runs in sandboxed Docker environment | M1 + M2 | Image/envelope in M1; agent execution inside container from M2 |
| REQ-14 | Structured run log per run | M2 | `logger.py` writes to SQLite |
| REQ-15 | Agent completion reported outcome captured | M2 | `AgentResult` parsed from agent output |
| REQ-16 | CLI command to review recent runs | M4 | `labro review` with filter flags |
| REQ-17 | Token/time costs aggregated by agent/model | M4 | Surfaced in `labro review` output |
| REQ-18 | Multi-project config; per-project schedule, stack, actions | M1 + M2 + M5 | Schema in M1; `LABRO_DISABLED` and `daily_budget_usd` in M2; cron generation in M5 |
| REQ-19 | New project onboarded with config change only | M4 | `labro init` completes label setup; no code changes required |
| REQ-20 | Label transitions as deterministic post-run step | M3 | `post_run.py`; extended in M6 and M7 |
| REQ-21 | Daily digest via Slack | M8 | `digest.py`; `labro digest [--dry-run]` |
| REQ-22 | Outcome signals from passive GitHub state | M8 | Digest job reads `items_touched`; writes signals back to SQLite |
| REQ-23 | 👍/👎 reactions as satisfaction signal | M8 | GitHub reactions API; surfaced in digest |
