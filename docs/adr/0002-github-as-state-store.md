# ADR-0002: Use GitHub labels as the state store for outcome tracking

* **Status:** Accepted
* **Date:** 2026-05-26

## Context

REQ-22 requires Labro to find items it acted on in prior runs and check their current GitHub state (merged, closed, reacted to). This requires a persistent record of which items Labro has touched.

Options considered:
- Scan JSON run log files on every run (O(n) in history depth)
- Maintain a sidecar index file (`acted_items.json`)
- Use GitHub labels — the state that already exists for task lifecycle management

## Decision

Use GitHub labels as the sole state store for outcome tracking. No sidecar file, no log scanning.

Every PR or issue Labro creates or acts on receives a universal marker label — **`ai-contributed`** — applied as part of the post-run step. REQ-22 is satisfied by querying GitHub for items carrying `ai-contributed` and reading their current state.

The `ai-contributed` label is intentionally generic: it does not embed the harness name, so it remains meaningful if other AI tooling is introduced later.

## Label naming convention

Labro labels use the prefix `ai-` but never embed the word `labro`. Rationale: labels are visible to all collaborators and should describe the nature of the contribution, not the internal tool that made it.

| Label | Applied by | Meaning |
| :--- | :--- | :--- |
| `ai-contributed` | harness, post-run | Universal marker: Labro created or acted on this item |
| `ai-dev-done` (example) | harness, post-run | `gh-label` task completed successfully |
| `ai-failed` | harness, post-run | Run failed; item skipped until operator clears label |
| `ai-alert:<rule-uid>` | agent, on creation | Issue tracks a specific Grafana alert rule |
| `ai-proactive-suggestion` | agent, on creation | Issue is a proactive improvement suggestion |

## Rationale

- GitHub is already the authoritative source for item state (merged, closed, reactions) — no need for a second store.
- Label queries are O(1) via the GitHub API regardless of run history depth.
- The existing label lifecycle (REQ-20) already touches every acted-on item; adding `ai-contributed` is a single extra step with no new mechanism.

## Consequences

- Outcome tracking (REQ-22) and satisfaction tracking (REQ-23) both query `ai-contributed`-labelled items.
- If an operator removes `ai-contributed` from an item, Labro loses visibility of that item for outcome tracking — accepted risk; documented in operator guide.
- The PR merge rate KPI (headline metric) is computed from PRs carrying `ai-contributed`, not from log files.
