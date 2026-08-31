# Changelog

## v0.17.2 — 2026-08-31

### Changed
- Each run now clones its target repo into a fresh, run-scoped directory
  (`repos_dir/run-<run-id>/<slug>`) instead of reusing one persistent working
  copy per repo, and deletes it when the run ends. The old reset-on-entry
  guard only covered a dirty working tree — agents have full shell access and
  can also leave behind a diverged branch, `.git/config` residue, stashes, or
  hooks, none of which a reset touches. (This had already caused an outage:
  an agent's `git push -u` left `branch.main.merge` pointing at a deleted
  remote branch, breaking every subsequent run for that repo.) Orphaned
  checkouts from a hard-killed run are swept on every run and removed after
  six hours. Clones are full, not shallow, so agents still see history. (#61)

### Fixed
- Dependency bump: `pip` 26.1.2 → 26.2.1 for PYSEC-2026-3721 (pulled in
  transitively via `pip-audit`).

### Documentation
- README now describes Dependabot handling accurately: Labro comments on
  Dependabot PRs cross-referenced against open security alerts, and raises a
  tracking issue for alerts Dependabot hasn't yet opened a PR for — it was
  previously described as "reviewing" Dependabot PRs.

### Internal
- `ci-python.yml` now runs `pip-audit` as its own `dependency-audit` job,
  separate from `ci` (ruff/mypy/bandit/pytest). A dependency advisory landing
  on an unrelated day used to abort `ci` before pytest ran, misreporting an
  unrelated commit as having broken tests.

## v0.17.1 — 2026-08-09

### Fixed
- Agent tool subprocesses could outlive the run that spawned them. Only the
  direct child was signalled, so grandchildren reparented to PID 1 and kept
  running — one saturated the host for 36 minutes. Each agent now gets its own
  process session and the whole group is torn down (SIGTERM → SIGKILL) on
  timeout *and* on normal exit; a second pass reaps any stray still carrying
  the run's `LABRO_RUN_ID`, scoped to that run so concurrent projects are
  unaffected. (#58)
- Dependency bump: `cryptography` 49.0.0 → 50.0.0 for CVE-2026-69247.

### Changed
- Dashboard now pins Node 22 via `.nvmrc` and declares `engines`, so an
  out-of-date Node warns at `npm ci` instead of failing later in the build.
- Dashboard dependencies updated (12 packages, incl. postcss 8.5.16 → 8.5.25)
  and `actions/setup-node` 6 → 7.

### Documentation
- README now documents the supported agents and the
  `agent:provider/model@effort` slug format — Codex support was previously
  invisible to a reader evaluating the project.
- QUICKSTART now names the correct Codex credential env var (the one the live
  deployment actually uses) and lists codex among the bundled CLIs.
- Deployment docs describe the compose-based deployment instead of a stale
  `docker run` block.

### Internal
- Pre-commit runs ruff/mypy/bandit from `uv.lock` rather than its own pins,
  ending a drift where hooks and CI enforced different rule sets in both
  directions. mypy now also covers `tests/`.
- OpenCode's duplicate subprocess helper collapsed into the shared `run_cli`,
  so process teardown lives in exactly one place.
- Test suite fails loudly on any attempt to signal a whole process group or
  every process — a mocked pid coercing to 1 would otherwise `kill(-1)` the
  developer's login session.
- `npm run preview` shares the R2 proxy with `npm run dev`.

## v0.17.0 — 2026-07-24

### Added
- Per-project publish gate for the dashboard snapshot. A new `publish`
  boolean (default `false`) on each project in `labro.toml` controls whether
  that project's runs are included in the public dashboard snapshot. Runs,
  items_touched, projects, and project_locks rows are all filtered to
  published projects only, so an unpublished project's name never ships in
  the snapshot — including transient `project_locks` rows during an in-flight
  run. The snapshot is VACUUMed after filtering as defensive hardening, so the
  no-residue guarantee holds regardless of the SQLite build's `secure_delete`
  setting.

### Changed
- **Action required on upgrade:** the dashboard snapshot now fails safe — a
  project publishes nothing until you set `publish = true` for it in
  `labro.toml`. Existing deployments must opt each project in explicitly or it
  will drop off the public dashboard.

## v0.16.10 — 2026-07-21

### Fixed
- OpenCode structured-output reliability on weak/free models (big-pickle,
  nemotron, etc.): the prompt now leads with an explicit mandate that the
  `outcome` key is always present, is one of the three literal values, and is
  never null or omitted — fixing intermittent `outcome … got None` validation
  failures. The JSON extractor also now unwraps a single-level wrapper object
  (e.g. `{"structured_output": {...}}`) instead of hard-failing on it.

## v0.16.9 — 2026-07-19

### Added
- Optional analytics snippet injection for the dashboard: set `ANALYTICS_SNIPPET_HTML` in the config repo to inject a tracking snippet (Umami, Plausible, GA, etc.) at deploy time. Unset by default — public builds ship with no tracking.

### Fixed
- Working copy artifacts left behind by the agent (e.g. a `.venv`) are now cleaned up after every run (`git reset --hard` + `git clean -fdx`), preventing unbounded disk growth on long-lived deployments
- Tool caches (pip-tools, pip, uv) are now cleared after every run for the same reason — a single dependency resolution could leave several GB behind
- Analytics snippet injection now actually matches the placeholder in `dashboard/index.html` (the deploy workflow's find/replace was a silent no-op)

### Changed
- Deployment docs now recommend docker-compose for VPS/crond mode instead of a bare `docker run`, for declarative recreates

## v0.16.8 — 2026-07-03

### Fixed
- `labro check` now reports FAIL when an agent CLI binary is not on PATH; unexpected invoke errors (e.g. a missing binary at runtime) are caught and recorded in the runs table instead of being lost
- `failure_reason` now summarises all fallback attempts, not just the last one
- Dashboard shows `—` for an empty agent instead of an internal default value
- `labro.example.toml`'s maintainer persona example brought in sync with the live config (prior pin audit and dependency conflict check steps were missing)

## v0.16.7 — 2026-06-25

### Fixed
- Pushgateway metrics now push on skipped and budget-exceeded runs, not just agent runs; the push was placed after the agent invocation so all early-exit paths bypassed it

## v0.16.6 — 2026-06-25

### Fixed
- `prometheus-client` is now included in the production Docker image (`.[metrics]` extra installed at build time); v0.16.5 silently skipped all Pushgateway pushes because the package was missing from the image

## v0.16.5 — 2026-06-25

### Added
- Optional Prometheus Pushgateway integration: set `PUSHGATEWAY_URL` to push `labro_last_run_timestamp` and `labro_run_duration_seconds` (with `project` and `outcome` labels) after each run. Requires `pip install labro[metrics]`. Silent no-op if the env var is absent.

## v0.16.4 — 2026-06-25

### Changed
- `gh-dependabot-alert` now skips alerts younger than 24 hours (configurable via `min_alert_age_hours`) so Dependabot has time to raise its own fix PR first
- `gh-dependabot-alert` skips alerts where Dependabot already has an open PR for the package
- `gh-dependabot-alert` deduplicates at package level — a second alert for the same package and manifest path is skipped even if it has a different GHSA ID

## v0.16.3 — 2026-06-21

### Fixed
- Container log output now appears in `docker logs`; the entrypoint tails `labro.log` to stdout so cron job output is visible without shelling into the container
- Bumped `undici` (dashboard dev dependency) to 7.28.0 to resolve security advisory
- Bumped `msgpack` to 1.2.1 to resolve GHSA-6v7p-g79w-8964

## v0.16.2 — 2026-06-17

### Fixed
- `gh-dependabot-alert` task source no longer re-creates an issue for the same Dependabot alert when a previous tracking issue was closed within the last 10 days; after 10 days a fresh issue may be raised

## v0.16.1 — 2026-06-17

### Fixed
- `labro run` no longer fails when `dashboard.enabled = true` but R2 credentials are absent from the environment; R2 env var validation is now deferred to the `publish-db` command where it's actually needed
- Bumped `cryptography` to 49.0.0 to resolve security advisory GHSA-537c-gmf6-5ccf
- Improved fetch error logging in `gh-dependabot-alert` task source; documented required Dependabot alerts permission in deployment guide

## v0.16.0 — 2026-06-16

### Added
- `gh-dependabot-alert` task source — harness can now pick up Dependabot security alerts and hand them to the agent
- Dashboard: mobile-optimised view with responsive layout
- Dashboard: ARIA roles and keyboard navigation for all interactive elements
- Dashboard: accessibility test harness (axe-core via vitest) run in CI

### Changed
- Dashboard: drawer UX synced with table row UX; shared formatter utilities extracted

## v0.15.0 — 2026-06-15

### Added
- `projects` table populated at publish time, enabling per-project filtering and drill-down in the dashboard

### Changed
- Bump pinned versions of Claude, Codex, and OpenCode agents
- Dashboard: dates now display in browser local time (sv-SE locale)
- Dashboard: minor text amendment

### Internal
- Extract shared dashboard constants; add `run-dashboard` dev skill

## v0.14.0 — 2026-06-14

### Added
- Perspectives pool expanded from 32 to 42 entries across 9 groups, giving the proactive-improvement task source a richer draw of angles

### Changed
- Dashboard: proactive suggestions now display the 🎭 icon; thumbs-up reactions swap to 💡

## v0.13.0 — 2026-06-14

### Changed
- `proactive-improvement` runs now use the agent-updated issue title as the task description in the dashboard. On success the title is fetched via `gh api` after the agent returns (the agent is prompted to rename the issue); on failure it falls back to the tidied perspective name (e.g. `red-team` → "Red Team").

## v0.12.0 — 2026-06-14

### Added
- Dashboard: agent column and filter, detail column, improved table layout
- Dashboard: richer source column using `source_description` field from runs

### Fixed
- `labro check` now loads config without an env check, reporting each missing variable individually rather than failing on the first
- `labro check` no longer runs a label pre-flight check — labels are auto-created at run time

### CI
- Daily prune of container versions older than 7 days

## v0.11.2 — 2026-06-12

### Fixed
- Container entrypoint now decodes `CODEX_AUTH_JSON_BASE64` env var into `~/.codex/auth.json` so Codex credentials injected as Docker secrets are picked up at startup

## v0.11.1 — 2026-06-12

### Fixed
- Missing agent auth configuration is now a warning rather than a hard `ConfigError`, allowing the run to proceed with other configured providers

### Docs
- Environment variable reference split into subsections with signal collection rationale added
- Quickstarts moved to `QUICKSTART.md`, `CONTRIBUTING.md` created, general README cleanup
- README intro trimmed, `WHY.md` consolidated, `DASHBOARD.md` created

## v0.11.0 — 2026-06-11

### Added
- Thumbs up/down reaction signal now shown in the runs table outcome column on the dashboard
- Model fallback now triggers on provider quota/credit exhaustion (`session_limit_hit`) in addition to timeouts, across all agent implementations (Claude Code, Codex, OpenCode)

### Fixed
- `collect-signals` no longer emits duplicate rows when the same item is touched in multiple runs
- pytest pre-commit hook no longer runs `uv sync`, preventing `uv.lock` conflicts during test runs

### Docs
- Docker quickstart overhauled to cover all providers end-to-end
- Codex fallback configuration examples added to `labro.example.toml`

## v0.10.2 — 2026-06-10

### Fixed
- Infrastructure failures (timeouts, rate limits, unsupported models) are now consistently detected as fallback conditions across all three agent implementations (Claude Code, Codex, OpenCode)
- Proactive improvement issues now include fallback notes in the issue body when the primary model fails and a fallback model is used

## v0.10.1 — 2026-06-10

### Fixed
- `collect-signals` now generates a GitHub App installation token before calling
  `gh api`, fixing 100% error rate on GitHub App-authenticated deployments

## v0.10.0 — 2026-06-10

### Added
- Dashboard: `fallback_attempts` column now visible in the runs table and detail drawer
- CI: Python and dashboard CI workflows; Dependabot coverage expanded to Actions and dashboard deps
- CI: CI status badges added to README; GitHub Releases now auto-created on version tag push

### Changed
- Perspectives: white-hat prompt narrowed to static evidence only, reducing speculative findings

### Fixed
- Removed stale `assignees` field from `Task` model

## v0.9.0 — 2026-06-09

### Added
- **Model fallback support** — configure a list of model slugs per project; if the primary model times out or is unavailable, Labro automatically retries with the next slug in the list. The number of fallback attempts is recorded in the `runs` table (`fallback_attempts` column).

## v0.8.0 — 2026-06-08

### Features
- **Multi-select outcome filter** — dashboard outcome filter now supports multiple selections, defaulting to success+failure
- **Dashboard hero text & GitHub link** — contextual hero text and a GitHub repository link added to the dashboard header
- **Configurable dashboard title** — dashboard title is now driven by `labro.toml` (`[dashboard] title`)

### Fixed
- **OpenCode error messages** — error event messages from OpenCode are now surfaced in `failure_reason`

### Docs
- Licence switched to Apache-2.0
- README restructured as a landing page; ops and deployment guides extracted to separate docs
- Live dashboard example link added to README

## v0.7.0 — 2026-06-05

### Features
- **Dashboard Charts (M9.2)** — new `Charts` tab with shared filter bar, 5 chart groups (cost trend, engagement, outcome trend, speed, token trend), and a duration-per-model graph
- **`[signals]` config section** — `collect-signals` cron scheduling is now config-driven via `labro.toml`; `gen-crontab` emits the cron line when `signals.enabled = true`; the `collect-signals` command back-fills outcome signals (`outcome_state`, `follow_up_commits`, 👍/👎) on `items_touched` rows by querying the GitHub API

### Fixed
- **Dashboard cost column** — zero and negative cost values handled gracefully

### Docs
- Split roadmap M8 into M8.1 (engagement metrics) and M8.2 (Slack digest)

## v0.6.0 — 2026-06-05

### Features
- **Dashboard per-project stats tab** — new tab showing aggregate stats per project
- **Dashboard tooltips** — inline explanations for core concepts throughout the UI

### Fixed
- **`gh-author` logging** — `match=security/standard` now included in the picked log line
- **Vite 8 compat** — bumped `@vitejs/plugin-react` to `^5.2.0`

### Docs
- Dashboard setup and `publish-db` walkthrough; M9.1 marked shipped
- Model selection guide with caveats and cross-repo examples

## v0.5.0 — 2026-06-05

### Features
- **`requires_dependabot_alert` on `AuthorRule`** — cross-references the repo's open Dependabot security alerts to identify security-update PRs and prioritise them above routine version bumps

### Fixed
- Log line prefix order: logger name now appears after the run context bracket, with ` - ` separator — `INFO [project abc12345] logger.name - msg`

## v0.4.0 — 2026-06-05

### Features
- **`gh-author` task source** — items matched by GitHub login (PRs/issues opened by a specific author) are now a dedicated source type, `gh-author`, with its own `author_rules` config field. `gh-label` retains `label_rules` only, making each source's name honest about what it watches.
- **Metrics dashboard SPA** — Vite + React + TypeScript single-page app (`dashboard/`) that loads a SQL.js WASM snapshot from R2 and renders a runs table with project, cost, and turn counts. Includes a drilldown drawer with full run field detail and responsive mobile layout.

### Changed
- `actor_rules` in `gh-label` source config renamed to `author_rules` (used in the new `gh-author` source); config must be updated if you previously used `actor_rules` under a `gh-label` source.
- `dashboard.bucket` moved from `labro.toml` to the `R2_BUCKET` environment variable; `DashboardConfig` no longer has a `bucket` field.

### Fixed
- Entrypoint startup log timestamp now includes milliseconds.

## v0.3.3 — 2026-06-04

### Features
- `labro publish-db`: snapshots `labro.db` via `VACUUM INTO` and uploads to Cloudflare R2
  with hand-rolled SigV4 auth (no new dependencies)
- New `[dashboard]` config block with `enabled`, `cron`, `bucket`, `key_prefix` fields;
  `enabled = true` requires `bucket` and the three `R2_*` env vars
- `labro gen-crontab` emits a `labro publish-db` cron line when `dashboard.enabled = true`

## v0.3.2 — 2026-06-03

### Features
- Improved run logging: per-run context prefix, UTC timestamps, and richer run-complete output line

### Fixed
- Label transitions now use the REST API, avoiding the deprecated Projects-classic API
- Container startup log line is now written to `labro.log` as well as stdout
- Graceful restart script: 5-minute timeout guard and `set -euo pipefail` to prevent an infinite wait if the DB is unavailable

## v0.3.1 — 2026-06-03

### Features
- Log Labro version on container startup; add `--version` CLI flag
- Dispatch `labro-release` webhook event to config repo after image publish

### Fixed
- Docker image: add OCI labels, guard `:latest` tag from pre-release builds, default `VERSION` to `SNAPSHOT`

## v0.3.0 — 2026-06-03

### Features
- Maintainer persona for Dependabot PR review

### Changed
- `GITHUB_APP_PRIVATE_KEY` and `GITHUB_APP_PRIVATE_KEY_BASE64` env vars renamed to `GH_APP_PRIVATE_KEY` and `GH_APP_PRIVATE_KEY_BASE64`; Docker defaults updated accordingly
