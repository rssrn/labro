# ADR 0007 — Read-Only Metrics Dashboard (sql.js SPA)

**Status:** Accepted
**Date:** 2026-06-04

## Context

Labro's observability is delivered via the daily digest (Slack) and `labro review` (terminal table). Both are linear, text-only views. The operator wants to *explore* run history visually — filter by timespan and across dimensions (project, model, task source), and see trends and breakdowns as charts (REQ-24).

The PRD's original v1 non-goal was "a web UI or dashboard". The constraint that matters is **no real-time or control surface** — nothing that triggers, pauses, or mutates runs, because that would undermine the cron + priority-picker model. A *read-only* viewer over already-recorded data does not touch that principle, so it is in scope post-v1 as M9.

Constraints that shaped the decision:

- The harness must stay simple and stateless with respect to the dashboard — no new server process, no API surface, no coupling.
- All metrics already live in `labro.db` (the `runs` and `items_touched` tables, with indexes on `runs(project, started_at, outcome)`).
- The data volume is tiny (one row per run; single-digit MB for years).
- Run records contain prose derived from potentially private repos.

## Decision

### Architecture — static SPA, no backend

The dashboard is a static single-page app that loads a **published snapshot** of `labro.db` and runs entirely in the browser. There is no backend and no live link to the harness. It is a separate deployable, not part of the harness Docker image.

### Data layer — sql.js (whole-file)

Use `sql.js` (SQLite compiled to WASM): download the whole snapshot once and run arbitrary SQL client-side. This avoids any export/transform step — schema changes are reflected automatically — and is the right choice while the DB is small.

**Upgrade path (deferred):** if the DB ever exceeds ~10 MB, switch the data layer to HTTP-Range paging (`sql.js-httpvfs` or equivalent). R2 already serves `Accept-Ranges`, and the existing indexes keep paged queries cheap. This is isolated behind the data-layer interface and changes nothing else.

### Framework — React 18 + Vite + TypeScript

Matches the operator's existing `newschart` toolchain (config, ESLint, vitest lift over almost verbatim). Reactivity keeps the shared filter bar driving both the table and the charts simple. Build output is static and uploaded to R2.

### Charts — Apache ECharts

Richest built-in interactivity (timespan brush-select, zoom, tooltips, legend toggling) with minimal config; lazy-loaded so it does not bloat first paint.

### Hosting — Cloudflare R2 + CDN

Static assets and the `.db` snapshot are served as plain objects from R2 behind Cloudflare. The SPA and the `/db/` path sit behind the **same custom domain**, so DB fetches are same-origin (no CORS).

### Publishing — `labro publish-db` + manifest

A new CLI command (M9) produces a consistent snapshot via `VACUUM INTO` (collapses WAL; no `-wal`/`-shm` sidecars; never copies the live file), then uploads it as `labro-<hash>.db` together with a `manifest.json` (content hash + `generated_at`). The SPA reads the manifest first (short TTL) and fetches the hashed filename (immutable TTL) — so a new snapshot is a new URL and the CDN never serves stale data without a manual purge. The command runs on its own cron, independent of project runs.

### Access control — deferred, warning only

Run records carry private-repo prose (`task_description`, `summary`, `failure_reason`, `item_url`). M9 **deliberately ships no access control** to keep the dashboard simple: protecting the published snapshot and SPA is the operator's responsibility, covered by a prominent warning in the README and deployment docs (the R2 bucket/URL is sensitive and must not be made public or linked from anywhere indexable). Built-in protection — Cloudflare Access (Zero Trust) in front of the SPA and `/db/`, and an optional free-text-column redaction mode in `labro publish-db` — is deferred to a later milestone if the simple posture proves insufficient. No secrets are written to run records, so the snapshot carries no credentials; the only exposure is potentially-private prose.

## Consequences

- A new top-level `dashboard/` directory in the labro repo with its own `package.json`/Vite build; not baked into the harness image.
- A new `labro publish-db` subcommand plus object-store config (bucket, endpoint, credentials via env) in `labro.toml`.
- Delivery is two-phase: (1) runs list + per-project stats; (2) trend/breakdown charts.
- The dashboard depends only on the published snapshot shape — it has no runtime coupling to the harness and cannot affect runs.
- Cross-reference: [ADR 0004](0004-sqlite-persistence.md) (SQLite is the single source of truth the snapshot is taken from).
