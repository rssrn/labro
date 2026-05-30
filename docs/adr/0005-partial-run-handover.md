# ADR 0005: Partial-run handover for turn-limit exhaustion

## Status

Accepted

## Context

When Claude Code hits its `--max-turns` limit mid-task, the CLI returns
`is_error: true`, `subtype: "error_max_turns"`, and no `structured_output`.
Previously Labro treated this as a hard runner error: cost data was discarded,
any in-progress code edits were silently reset on the next run, and the ticket
received a generic `ai-failed` label and an unhelpful comment.

Two concrete problems:

1. **Silent money leak** — `total_cost_usd` from a burned max-turns run was
   never recorded, making daily-budget tracking inaccurate.
2. **Work lost** — the agent may have written code or posted analysis; both
   were discarded, forcing a full re-run from scratch.

## Decision

`"partial"` is now a first-class outcome with its own recovery path:

**Runner** — when `structured_output` is absent and `subtype == "error_max_turns"`,
build an `AgentResult(outcome="partial")` from salvaged fields (`result`,
`total_cost_usd`, token counts) instead of raising `RunnerOutputError`. Any
other missing-SO case returns `outcome="failure"` with cost preserved. A
present-but-malformed `structured_output` still raises (contract violation).

**Store** — `"partial"` is added to the `runs.outcome` CHECK constraint.
`open_db` detects pre-migration DBs (those lacking `'partial'` in the stored
table SQL) and rebuilds the table in a single transaction.

**WIP preservation** — after any non-success agent run, `repo.preserve_wip`
checks `git status`. If the working copy is dirty, it creates a
`labro-wip/<run-id>` branch, commits all changes, and pushes. Best-effort:
failures are logged and never propagate to the run loop. The WIP namespace is
clearly separable from project branches.

**Post-run** — `outcome == "partial"` applies `ai-handover` + `ai-contributed`
and posts a structured handover comment that includes the agent's last message,
the WIP branch URL (if any), and the re-trigger instruction ("Remove
`ai-handover` to re-queue"). For `outcome == "failure"` with a WIP branch, the
branch URL is appended to the existing failure comment.

**Picker** — `ai-handover` is excluded alongside `ai-failed` in both
`label_rules` and `actor_rules` loops. Removing `ai-handover` re-queues the
item with no other changes required.

**Prompt** — when the task has an in-scope item and a comment action is
permitted, the role section includes a short paragraph asking the agent to post
an early progress comment and update it in place (`gh issue comment --edit-last`).
This is not turn counting — just a durability nudge so analysis survives even
if no code is editable.

## Rationale

- **Deterministic harness** — the recovery is fully in the harness, not the
  agent. The agent cannot reliably observe its own turn counter in a `-p`
  one-shot; the harness detects `error_max_turns` unconditionally.
- **Human re-trigger** — `ai-handover` mirrors the `ai-failed` pattern: a
  single label removal re-queues the item. No new tooling or UI required.
- **Best-effort WIP** — WIP preservation can fail (push denied, network error)
  without blocking the run record. The log carries the warning; the operator
  can inspect the local copy if needed.
- **Cost visibility** — even a failed partial run records `total_cost_usd` so
  daily-budget accounting is accurate.

## Consequences

- Operators will see `ai-handover` on items where the agent ran out of turns.
  They must actively remove this label to retry — intentional friction to avoid
  repeated max-turns burns without a config change.
- The `labro-wip/` branch namespace will accumulate branches over time.
  Cleanup is manual (or can be automated outside the harness).
- A small one-time migration runs on first `open_db` call against a
  pre-0005 database. The migration is idempotent and no-ops on fresh or
  already-migrated databases.
