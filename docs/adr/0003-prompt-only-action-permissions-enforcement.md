# ADR-0003: Prompt-only enforcement for action permissions in v1

* **Status:** Accepted
* **Date:** 2026-05-26

## Context

The Action Permissions (e.g. `comment`, `open-pr`, `merge`) is declared per project and per task source in config. Labro must communicate this boundary to the agent and, ideally, enforce it.

Two enforcement mechanisms were considered:

1. **Prompt-only** — the action permissions is included in the constructed prompt as an explicit instruction. The agent is trusted to follow it.
2. **`gh` wrapper script** — a generated shell script replaces the real `gh` binary on `$PATH` in the agent's environment. Out-of-scope calls fail fast with a clear error. The real `gh` binary is not accessible to the agent.

## Decision

Use prompt-only enforcement in v1. The action permissions is communicated via the prompt; no wrapper script is generated.

## Rationale

* **Simplicity** — generating, injecting, and maintaining a parameterised wrapper script adds meaningful implementation complexity for a v1 system.
* **Observed model behaviour** — Claude Code follows explicit prompt instructions reliably in practice; hard enforcement is unlikely to be exercised in normal operation.
* **Bypassability either way** — the wrapper only covers `gh` CLI calls; direct GitHub API calls over HTTP bypass it regardless. Full containment was never achievable without network-level controls, so partial containment via a wrapper adds limited marginal safety.
* **Audit logs as compensating control** — every run is logged with `actions_taken`; out-of-scope actions are detectable after the fact.

## Alternatives rejected

* **`gh` wrapper** — adds complexity; still bypassable via direct HTTP; deferred to v1.1 if prompt-only proves insufficient.

## Consequences

* The Action Permissions is advisory in v1 — the agent could theoretically exceed it.
* If audit logs reveal systematic permission violations, a `gh` wrapper is a well-defined v1.1 hardening path.
* Risk is accepted as Low–Medium likelihood / High impact (see architecture risk register).
