# Changelog

## Unreleased

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
