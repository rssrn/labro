# M5 Red-Team Review

Date: 2026-05-31
Perspective: red-team
Scope: local repository review
Run: manual
Roadmap point: M5

## Summary

Labro's core shape is good: small deterministic harness, config-driven
priorities, explicit run records, dry-run mode, lock handling, and WIP
preservation are all the right primitives.

Through a red-team lens, the main question is where Labro can fail in a way
that surprises the operator. The biggest concern is that the project describes
a tight permission envelope, but some of the current enforcement boundaries are
still broader than they appear.

## Findings

### 1. Permission enforcement is still trust-heavy

The prompt says permissions are bounded, and Claude Code gets an
`--allowedTools` list, but the baseline tools include broad patterns such as
`Bash(gh api *)` and local `Edit`/`Write` in `src/labro/runner.py`.

`gh api *` can perform writes depending on method and flags, so it weakens the
permission envelope. This is the biggest red-team concern.

Recommended mitigation: remove `gh api *` from the baseline allowed tools, or
replace it with narrowly scoped read-only commands. Treat `--allowedTools` as
the real enforcement layer, with the prompt as explanation only.

### 2. Comment permissions are intentionally fuzzy

`src/labro/prompt_builder.py` omits comment actions from the forbidden list even
when they are not explicitly granted. That is pragmatic, but it means "no
GitHub writes" is not truly no writes if the agent can still comment via
allowed tools or broad API access.

Recommended mitigation: decide whether comments are part of the permission
model or outside it. If they are part of it, make the prompt and allowed tools
match exactly.

### 3. Crontab generation is vulnerable to config injection

Project `cron`, `project.name`, and `LABRO_LOG_PATH` are interpolated directly
into cron lines in `src/labro/cli.py`.

Since config is operator-controlled this may be acceptable, but if the config
repo is compromised, cron becomes command execution inside the container with
Labro's secrets and mounted volumes.

Recommended mitigation: validate cron fields, quote or sanitize project names,
and reject shell metacharacters in generated command fields.

### 4. Repo cache path can collide across owners

`src/labro/repo.py` stores repos under only the repository name, not the full
owner/repo slug. For example, `alice/api` and `bob/api` both map to the same
cache path.

In a multi-project setup this can cause cross-repo contamination or accidental
operations against the wrong remote.

Recommended mitigation: store repos under an owner-safe slug such as
`owner__repo`.

### 5. Dirty worktree reset can destroy useful evidence

Existing cached repos are reset and cleaned before pulling. The README says WIP
preservation handles interrupted work, but any preservation failure followed by
a later run can erase local changes.

Recommended mitigation: preserve or snapshot dirty state before reset, or make
the reset path record enough detail that the operator can understand what was
removed.

### 6. Proactive-improvement schema appears ahead of implementation

The schema includes `ProactiveImprovementSource`, but the source tree does not
currently show `task_sources/proactive_improvement.py`.

Recommended mitigation: either keep docs clear that proactive improvement is not
yet implemented at M5, or add an explicit source implementation before
advertising it as available behavior.

## Docker Mitigation Notes

Running inside Docker helps with host protection, reproducibility, disposable
runs, and limiting accidental access to the host filesystem.

Docker does not fully mitigate GitHub write blast radius, repo damage inside
bind-mounted `/repos` and `/data`, config-generated command execution inside
the container, cross-repo cache collisions, or cost burn. The GitHub token,
Claude credentials, mounted volumes, and allowed tool patterns remain the main
authority boundaries.

In short: Docker is a useful host sandbox, but it is not a complete authority
sandbox. The most important boundary for Labro is still the combination of
narrow GitHub tokens, narrow Claude Code `--allowedTools`, conservative bind
mounts, and per-project budgets.

## Recommended M5 Priorities

1. Remove or narrow `Bash(gh api *)` from baseline allowed tools.
2. Make comment permissions explicit and consistent between prompt and tools.
3. Change repo cache paths from repo name to owner/repo slug.
4. Add validation around crontab generation fields.
5. Clarify proactive-improvement implementation status in docs or complete the source.
