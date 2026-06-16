# Labro — Operations Reference

This document covers the run loop internals, environment variables, label transitions, signal collection, and the full CLI reference.

## Live Run Loop

When you run `labro run <project>` without `--dry-run`, the harness executes the following steps in order:

1. **Load config** — parse and validate `labro.toml` (or `$LABRO_CONFIG`)
2. **Check `LABRO_DISABLED`** — if `/data/LABRO_DISABLED` exists, print `skipped: harness disabled` and exit immediately; no lock is acquired and no SQLite record is written
3. **Acquire run lock** — INSERT into `project_locks`; if a non-stale lock already exists, print `skipped: run in progress` and exit
4. **Budget check** — if `daily_budget_usd` is configured, query today's spend from `runs`; if the limit is reached, write a skipped record to SQLite and exit
5. **Pick task** — run the picker over all configured task sources; if nothing is found, write a skipped record and exit
6. **Prepare repo** — clone or pull the target repo into `/repos/<slug>`; if the working copy is dirty (agent was interrupted mid-edit), log a warning then `git reset --hard && git clean -fd`
7. **Build prompt** — construct the four-section prompt from the resolved task and project context
8. **Invoke agent** — run `claude -p` as a subprocess with the prompt on stdin; validate the `structured_output` payload. If the model slug is a list, each slug is tried in order on infrastructure failure; the first successful or non-infrastructure-failure outcome wins. Fallback attempts are recorded in `fallback_attempts` in the `runs` table. If the agent hits its turn limit (`--max-turns`), the harness recovers gracefully — see [Turn Limits and Partial Runs](#turn-limits-and-partial-runs) below
9. **Preserve WIP** — on any non-success outcome, if the working copy is dirty the harness commits it to a `labro-wip/<run-id>` branch and pushes it, so no in-progress code edits are silently discarded
10. **Post-run labels** — apply label transitions and post a comment to the GitHub item (see [Label Transitions](#label-transitions))
11. **Write run record** — INSERT a row into `runs` with outcome, cost, token usage, and action list
12. **Release lock** — DELETE from `project_locks` (always; in a `finally` block)

## Required Environment Variables

### GitHub Authentication

Choose one method:

- **`GH_TOKEN`** — GitHub PAT. See [GitHub Token Setup](DEPLOYMENT.md#github-token-setup).
- **`GH_APP_PRIVATE_KEY`** — Raw PEM private key for a GitHub App (local/plain deployments). Replaces `GH_TOKEN`.
- **`GH_APP_PRIVATE_KEY_BASE64`** — Base64-encoded PEM (`base64 -w 0 your-app.pem`). Takes precedence over `GH_APP_PRIVATE_KEY` if both are set; intended for container/CI environments.

### Agent Authentication

At least one agent provider must be configured:

- **`CLAUDE_CODE_OAUTH_TOKEN`** — OAuth token from `claude setup-token` for the claude-code agent. Tied to your Pro/Max subscription.
- **`ANTHROPIC_API_KEY`** — API key for the claude-code agent billed pay-per-token. If **both** this and the OAuth token are set, the API key takes precedence.
- **`OPENROUTER_API_KEY`** — API key for the opencode agent when using OpenRouter.
- **`CODEX_API_KEY`** — API key for the codex agent via OpenAI API (pay-per-token billing).

### Labro Runtime

All optional; sensible defaults for single-mount Docker layout:

- **`LABRO_CONFIG`** — Path to `labro.toml` inside the container (default: `./labro.toml`).
- **`LABRO_REPOS_DIR`** — Where repos are cloned (default: `/repos`; use `/data/repos` with single-mount layout).
- **`LABRO_DB_PATH`** — SQLite database path (default: `/data/labro.db`).
- **`LABRO_LOG_PATH`** — Log file path (default: `/data/labro.log`).

### Dashboard (R2)

Required only when `[dashboard] enabled = true` in `labro.toml`:

- **`R2_ACCESS_KEY_ID`** — Cloudflare R2 S3 API access key.
- **`R2_SECRET_ACCESS_KEY`** — Cloudflare R2 S3 API secret key.
- **`R2_ACCOUNT_ID`** — Cloudflare account ID (endpoint derived automatically).
- **`R2_BUCKET`** — R2 bucket name. Used by the CI workflow (`dashboard-publish.yml`) to upload SPA assets; the harness reads the bucket from `[dashboard] bucket` in `labro.toml`.

## Emergency Pause — `LABRO_DISABLED`

To stop Labro from picking up new tasks without restarting containers:

```bash
# Pause — create the flag file in the /data volume:
touch /data/LABRO_DISABLED

# Resume — remove it:
rm /data/LABRO_DISABLED
```

The check happens before lock acquisition. Any run already in progress finishes normally; only new runs are blocked.

## Turn Limits and Partial Runs

Labro is designed for budget-conscious use. Low `max_turns` values keep costs predictable, but they mean the agent will sometimes hit its limit mid-task — especially on larger issues. This is expected and handled as a first-class outcome rather than a hard error.

When the agent exhausts its turn budget:

1. **Cost is recorded** — `total_cost_usd` and token counts are salvaged from the CLI response and written to the `runs` table as normal, so daily-budget accounting stays accurate even for incomplete runs.
2. **Code is preserved** — if the agent made any file edits before being cut off, the harness commits them to a `labro-wip/<run-id>` branch and pushes it to the remote. The branch URL appears in the handover comment.
3. **Handover comment posted** — Labro comments on the issue/PR with the agent's last message, a link to the WIP branch (if any), and the instruction to remove `ai-handover` to re-queue.
4. **Item is parked** — the `ai-handover` label is applied. The picker will not re-attempt the item until a human reviews the comment and removes the label — intentional friction to avoid burning the turn budget again without a config change.

> **Tuning tip:** if an item is repeatedly hitting the turn limit, either raise `max_turns` for that project/rule in `labro.toml`, or break the issue into smaller scoped tasks before re-queuing.

The prompt also asks the agent to post an early progress comment on the item and update it in place as work proceeds (`gh issue comment --edit-last`). This way analysis work is visible on the ticket even if the session ends before the agent can fill in `structured_output`.

## Label Transitions

After each live run, Labro updates the GitHub labels on the acted-on item automatically. The exact transitions depend on the task source rule type and the run outcome.

### `label_rule` Path (Label-Triggered Tasks)

| Outcome | Labels added | Labels removed |
|---|---|---|
| success | `<done_label>` (e.g. `ai-dev-done`), `ai-contributed` | `<source_label>` (e.g. `ai-dev`) |
| partial (turn limit) | `ai-handover`, `ai-contributed` | _(none — source label kept)_ |
| failure | `ai-failed`, `ai-contributed` | _(none — source label kept)_ |

### `gh-author` Path (Author-Triggered Tasks, No Source Label)

| Outcome | Labels added | Labels removed |
|---|---|---|
| success | `<done_label>`, `ai-contributed` | _(none)_ |
| partial (turn limit) | `ai-handover`, `ai-contributed` | _(none)_ |
| failure | `ai-failed`, `ai-contributed` | _(none)_ |

### Re-Queuing Items

**After a partial run (`ai-handover`):** review the handover comment (and WIP branch if present), then remove `ai-handover` to re-queue:

```bash
gh issue edit <number> --remove-label "ai-handover" --repo <owner/repo>
```

**After a failure (`ai-failed`):** remove `ai-failed` to re-queue (`ai-contributed` can stay — it's informational and never blocks re-pickup):

```bash
gh issue edit <number> --remove-label "ai-failed" --repo <owner/repo>
```

If the task was label-triggered, also ensure the source label (e.g. `ai-dev`) is still present.

### `proactive-improvement` Path

Labro creates the GitHub issue before the agent runs, applying `ai-proactive-suggestion` at creation time. The agent's task is to investigate and post findings as a comment.

| Outcome | Labels added to created issue | Notes |
|---|---|---|
| success | `ai-contributed` | `ai-proactive-suggestion` already applied at creation |
| failure | `ai-failed`, `ai-contributed` | Failure reason posted as a comment |

The `ai-proactive-suggestion` label counts toward the open-suggestion cap (`max_open_suggestions`, default 3). Close or relabel an issue to make room for a new proactive run.

### `gh-dependabot-alert` Path

Labro creates the GitHub issue before the agent runs, applying `ai-dependabot-alert` (configurable via `alert_label`) at creation time. The agent's task is to investigate the alert and open a fix PR.

| Outcome | Labels added to created issue | Notes |
|---|---|---|
| success | `ai-contributed` | `ai-dependabot-alert` already applied at creation |
| failure | `ai-failed`, `ai-contributed` | Failure reason posted as a comment |

There is no open-issue cap — dedup is handled by checking whether an existing `ai-dependabot-alert` issue already contains the alert's GHSA ID. Close the tracking issue once the fix PR is merged to keep the list tidy.

## Daily Budget Cap

Add to your project stanza in `labro.toml` to cap per-project spending per calendar day (UTC):

```toml
[[projects]]
name             = "my-project"
repo             = "my-org/my-repo"
daily_budget_usd = 2.00    # skip if today's spend already >= $2.00
```

Omit the field (or set it to `0`) to disable the cap. When the budget is exceeded, Labro writes a `skipped` record to SQLite with the reason `skipped: daily budget exceeded ($X.XX of $Y.YY used)` and exits without invoking the agent.

## `items_touched` Table

Labro writes a row to the `items_touched` SQLite table **before** the agent runs, as soon as the task is selected. This means the row exists even if the agent times out or crashes — it records which item was attempted, not whether the attempt succeeded.

```sql
SELECT repo, item_type, item_number FROM items_touched;
```

## Proactive Improvement — Perspectives

A **perspective** is a prompt lens that shapes the agent's approach for a single proactive run. Labro picks one at random from `perspectives.toml` (adjacent to `labro.toml`) each time the source fires.

**Setup:**
1. Copy `perspectives.toml` from the repo root into the same directory as your `labro.toml`.
2. Edit the perspective prompts to suit your project.
3. Restart Labro (or let it pick up the file on the next cron tick — it reads it fresh each run).

If `perspectives.toml` is absent, Labro logs a notice and runs without a perspective (agent has free rein).

**Restricting perspectives per project:** list the names you want:

```toml
[[projects.task_sources]]
type         = "proactive-improvement"
perspectives = ["red-team", "pre-mortem"]   # only these two, picked randomly
```

Omit `perspectives` (or set it to `[]`) to pick from all perspectives defined in the file.

**Adding custom perspectives** — append to `perspectives.toml`:

```toml
[perspectives.dependency-audit]
prompt = """
Review all third-party dependencies. Identify any that are outdated, unmaintained,
or have known vulnerabilities. Propose a concrete upgrade or replacement plan.
"""
```

**The chosen perspective** is written to the `runs` table (`chosen_perspective` column) and appears in the issue header, so every suggestion is auditable.

## Inspecting Run Records

### `labro review` (Recommended)

`labro review` prints a formatted table of recent runs directly from the SQLite database:

```bash
docker exec labro labro review --limit 10
docker exec labro labro review --project my-project --outcome failure
```

Flags:

| Flag | Default | Description |
|---|---|---|
| `--limit N` | 20 | Maximum runs to show |
| `--project NAME` | _(all)_ | Filter to one project |
| `--outcome` | _(all)_ | One of `success`, `failure`, `partial`, `skipped` |
| `--db-path PATH` | `/data/labro.db` | Override DB path |

The footer shows total runs, total cost, and total token usage across the displayed rows.

### Raw SQLite

The database is at `/data/labro.db` inside the container, bind-mounted to wherever you point `--volume` on the host.

**Everything for one run:**

```bash
sqlite3 -column -header /data/labro.db "
  SELECT * FROM runs          WHERE run_id = '<run_id>';
  SELECT * FROM items_touched WHERE run_id = '<run_id>';
"
```

**Items touched in a specific run:**

```bash
sqlite3 -column -header /data/labro.db \
  "SELECT * FROM items_touched WHERE run_id = '<run_id>';"
```

> **Tip:** `-column -header` formats output as aligned columns with a header row. Add `-json` instead for JSON output, or `-csv` for CSV.

## Signal Collection

The agent self-reports its outcome as `success`, `failure`, or `partial` at the end of every run, but that's a subjective hint — you don't actually know whether the work was useful until you see what happened next on GitHub. Signals fill that gap by collecting objective, post-hoc outcomes: was the PR merged or closed unmerged? was the issue closed as completed or not planned? did anyone react to the work? Over time this lets you gauge real effectiveness — which projects, model slugs, perspectives, and task sources actually produce value — rather than relying on the agent's own assessment.

Labro records which items (issues/PRs) were touched during each run in the `items_touched` table. The signal columns — `outcome_state`, `follow_up_commits`, `thumbs_up`, `thumbs_down` — are left NULL when the row is first inserted. The `labro collect-signals` command back-fills these columns by querying the GitHub API after the fact.

### Signal Columns

| Column | Type | Meaning |
|---|---|---|
| `outcome_state` | string | One of `merged` (PR), `closed_completed`, `closed_not_planned`, `closed_unmerged` (PR), or `open` |
| `follow_up_commits` | integer | Commits pushed to a PR *after* the run started (PRs only; `NULL` for issues) |
| `thumbs_up` | integer | Count of +1 reactions on the item |
| `thumbs_down` | integer | Count of -1 reactions on the item |
| `signals_collected_at` | timestamp | When the row was last refreshed (UTC) |

### Usage

```bash
labro collect-signals                              # default: stale-days=7
labro collect-signals --dry-run                    # print what would be written
labro collect-signals --stale-days 0               # only uncollected items
labro collect-signals --stale-days 14              # re-collect after 14 days
```

- **First run** collects every row that has never been touched, regardless of age.
- **Subsequent runs** skip rows that have already been collected, *unless* the outcome was `open` and the collection is older than `--stale-days` (default 7). This catches state transitions like issue closures or PR merges that happened after the initial collection.
- Partial success is normal: if one API call fails (e.g. the repo was deleted), the command logs a warning, increments the error counter, and continues with the next item.

### Scheduling

Add a `[signals]` section to `labro.toml` to control the cron schedule:

```toml
[signals]
enabled = true
cron    = "0 6 * * *"
```

The `labro gen-crontab` command emits the signal-collection cron line automatically from this config. The defaults (`--stale-days 7`) mean a weekly refresh of open items is sufficient, but running daily is harmless — already-collected closed items are skipped on subsequent passes.

---

## CLI Reference

All subcommands read `--config` (default: `$LABRO_CONFIG` or `./labro.toml`) from the global flag.

### `labro run <project> [--dry-run]`

Executes a single run for the named project. With `--dry-run`, resolves and prints the task, agent config, and full prompt without spending tokens or writing side effects.

### `labro init [--project NAME]`

Creates all GitHub labels referenced in `labro.toml` across every enabled project. Uses `gh label create --force` — idempotent, safe to re-run. Exits 1 if any label creation fails (but continues to attempt the rest).

```bash
labro init                        # all enabled projects
labro init --project my-project   # one project only
```

Run this once when onboarding a new project, or after adding new label rules to `labro.toml`.

### `labro check [--project NAME]`

Pre-flight health check — validates config, environment variables, GitHub connectivity, label presence, and (optionally) collaborator access. Read-only, no side effects.

```bash
labro check
labro check --project my-project
```

Each line is prefixed with `OK  `, `WARN`, or `FAIL`. Exits 1 if any `FAIL` is present.

- **`ANTHROPIC_API_KEY`** — validated by calling `GET /v1/models` (no tokens spent)
- **`CLAUDE_CODE_OAUTH_TOKEN`** — presence only; value cannot be validated without a live API call
- **`gh auth status`** — confirms the GitHub token is authenticated
- **Labels** — checks that every label referenced in config exists on each repo
- **`claude_assignee`** — if set in config, verifies the user is a collaborator on each repo

### `labro review [--limit N] [--project NAME] [--outcome OUTCOME] [--db-path PATH]`

Prints a formatted table of recent runs from SQLite. See [Inspecting Run Records](#inspecting-run-records) for full details.

### `labro list-locks [--db-path PATH]`

Shows currently held project locks with their age. Locks older than `timeout_s + 60` seconds are marked `[STALE]`.

```bash
labro list-locks
```

If a lock appears stale (the run that acquired it has clearly finished or crashed), use `labro unlock` to release it.

### `labro unlock <project> [--db-path PATH]`

Manually releases a stale project lock so the next scheduled run can proceed.

```bash
labro unlock my-project
```

This is a last-resort recovery tool. Under normal operation locks are released automatically in a `finally` block at the end of every run. A lock only gets stuck if the container was killed mid-run before the `finally` block executed.

### `labro publish-db [--dry-run] [--db-path PATH] [--snapshot-path PATH]`

Publishes a consistent snapshot of `labro.db` to R2 for the metrics dashboard.

```bash
labro publish-db                               # upload snapshot + manifest to R2
labro publish-db --dry-run                     # print hashed db_key + manifest; no upload
labro publish-db --db-path /data/labro.db      # override DB path
labro publish-db --snapshot-path /tmp/snap.db  # keep snapshot file after upload
```

Requires `[dashboard] enabled = true` and the three `R2_*` env vars. If the dashboard is disabled, the command prints a notice and exits 0. If creds are missing or the upload fails, it exits 1.

The snapshot is taken via `VACUUM INTO` (collapses WAL; never copies the live file while it may be open). The hashed filename (`db/labro-<sha256[:16]>.db`) means every new snapshot is a new URL and CDN caches never go stale without a purge. The DB is always uploaded before the manifest.

### `labro gen-crontab`

Emits crontab entries for all configured projects to stdout. Used by `entrypoint.sh` (VPS mode) to install `/etc/cron.d/labro`.

```bash
labro gen-crontab
```

### `labro collect-signals [--dry-run] [--stale-days N]`

Back-fills signal columns in `items_touched`. See [Signal Collection](#signal-collection) for full usage.
