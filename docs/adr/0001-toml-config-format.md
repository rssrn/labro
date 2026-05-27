# ADR-0001: Use TOML for configuration file format

* **Status:** Accepted
* **Date:** 2026-05-26

## Context

Labro needs a human-editable configuration file (`labro.toml`) that operators use to declare projects, cron schedules, priority lists, and per-source agent/permission overrides. The priority list is an array of heterogeneous objects — the dominant data shape in the config.

Candidates considered: TOML, YAML, JSON, Python module, SQLite.

## Decision

Use TOML (`labro.toml`). Parse with `tomllib` (Python 3.11+ stdlib). Validate the parsed dict with Pydantic.

## Rationale

* **Strict typing by default** — no Norway problem, no implicit boolean coercion (`yes`/`on`/`true` are not synonyms).
* **`[[array-of-tables]]` syntax** maps directly to the priority list (an ordered list of task source objects, each with optional overrides).
* **Zero extra parse dependency** — `tomllib` is stdlib since Python 3.11; write support via `tomli-w` if needed.
* **Operator-friendly** — comments supported; indentation not significant; harder to corrupt silently than YAML.

## Alternatives rejected

* **YAML** — implicit type coercion and indentation sensitivity introduce silent errors in hand-edited files.
* **JSON** — no comments; hostile to hand-editing.
* **Python module** — arbitrary code on load; incompatible with a future web UI.
* **SQLite** — "db-as-config" anticipates a web UI that is explicitly out of scope for v1 and only speculative beyond that.

## Consequences

* Config file is named `labro.toml`, not `labro.yaml`.
* `tomllib` (stdlib) handles parsing; Pydantic handles schema validation at startup.
* Write-back (if ever needed — e.g. a future CLI that edits config) requires `tomli-w`.
