# ADR-0004: Use SQLite as the persistence layer

* **Status:** Accepted
* **Date:** 2026-05-26

## Context

Labro needs to persist execution records and make them queryable — by the daily digest, by a future review CLI, and by outcome signal collection. The initial architecture proposed JSON log files.

## Decision

Use SQLite (`labro.db`) as the sole persistence layer. The file is bind-mounted from the host so it survives container restarts. Access is mediated via `store.py`.

## Rationale

* **Queryable** — the digest and outcome signal jobs need to aggregate, filter, and join records across runs and projects. SQL is the right tool; parsing JSON files is not.
* **No external service** — SQLite is a file, not a server process. It satisfies the operational simplicity constraint ("no external database service").
* **Python stdlib** — `sqlite3` ships with Python; no additional dependency.
* **Single file** — easy to back up, inspect, and bind-mount.

## Alternatives rejected

* **JSON log files** — not queryable without loading and parsing all files; awkward for aggregation; no schema enforcement.
* **PostgreSQL / MySQL** — external service; adds operational complexity incompatible with the single-container deployment model.

## Consequences

* `store.py` owns the schema and all read/write access; no other module touches SQLite directly.
* The bind-mount path is `/data/labro.db` inside the container.
* The database must be opened in WAL mode (`PRAGMA journal_mode=WAL`) to support concurrent writers across simultaneous project runs.
* A periodic purge of records older than N days should be added before sustained daily operation to prevent unbounded growth.
