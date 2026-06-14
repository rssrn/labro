# Changelog

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
