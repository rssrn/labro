# ADR 0008: Remove WIP-branch preservation and resume

## Status

Accepted (2026-09-02) — supersedes [ADR-005](0005-partial-run-handover.md) in part.

## Context

[ADR-005](0005-partial-run-handover.md) gave a cut-short run a recovery path:
push the dirty working copy to `labro-wip/<run-id>`, label the item
`ai-handover`, post a comment offering the branch, and resume from it on the
next run once a human removed the label.

Across 1,999 recorded runs (98 of which invoked an agent), the loop never
completed once:

- **3 runs** ever produced a `wip_branch_url`, all three the same opencode
  provider error — a dead agent, not interrupted work.
- **0 resumes, ever.** `prior WIP branch found` never appears in `labro.log`.
- **`ai-handover` was never applied by a live run**, so the human half of the
  loop was never exercised.
- The two halves could not meet anyway: `preserve_wip` fired on *any*
  non-success outcome, but `store.get_prior_wip_run` filtered on
  `outcome = 'partial'`, and all three preserved branches were `failure` rows.

Meanwhile the feature cost ~68 references across seven source modules, seven
test files and the dashboard, and left orphan branches on public repos.

The capability it duplicated already exists: agents hold `push_default` and
push their own branches as they work. Every genuine `partial` run
(`error_max_turns`) left a clean tree — the agent had already pushed.

## Decision

Remove WIP preservation and resume entirely.

- **Deleted** — `repo.preserve_wip`, the `wip_branch` resume path in
  `repo.prepare_repo` (it now returns a plain `Path`), `store.get_prior_wip_run`,
  the resume section of the prompt, the `ai-handover` label (both the
  `post_run` write and the two task-source exclusions), and the
  `wip_branch_url` / `resuming_wip` arguments of `post_run` and `write_run`.
- **Kept** — the `partial` outcome. It is agent-reported (it is in the agent
  JSON schema for all three providers) and it is what makes a turn-limit run
  distinguishable from a crash in the dashboard. `post_run` now routes it
  through the failure path: `ai-failed` + `ai-contributed`, and a comment that
  names the turn limit and the failure reason.
- **Kept** — the `runs.wip_branch_url` column, nullable and never written. The
  three historical rows still render in the dashboard.
- **Added** — `repo.summarize_dirty_tree`, called on any non-success outcome.
  One log line (`N uncommitted path(s)` plus a diffstat) answers the only
  question the WIP branches were ever asked: did the agent lose real work?

## Consequences

- A turn-limit run is now indistinguishable from a failure *on GitHub*: it gets
  `ai-failed`, and an operator re-queues it by removing that label. The
  distinction survives in the `runs` table and the dashboard.
- Nothing the agent leaves uncommitted is recoverable after the run. If the log
  line starts showing real work being discarded, that is the signal to
  reconsider — not the absence of the feature.
- The harness no longer writes to a managed repo outside `permitted_actions`.
- The orphan `labro-wip/*` branches on `rssrn/birdbird` and `rssrn/newschart`
  were deleted as part of this change.

Related: rssrn/labro#62.
