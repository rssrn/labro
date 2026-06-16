# Labro — CLAUDE.md

## What This Is

Labro is a self-hosted harness that runs Claude Code as a subprocess to perform autonomous maintenance on GitHub repos (triage issues, review PRs, investigate alerts). The harness is deliberately simple — deterministic, auditable orchestration. The agent is smart; Labro just selects a task, builds a prompt, and records the result.

## Tech Stack

- **Language**: Python 3.12+, managed with `uv`
- **CLI**: argparse (`labro run <project>`, `labro gen-crontab`)
- **Config**: TOML (`labro.toml`), validated with Pydantic 2
- **GitHub**: `gh` CLI subprocess (not a Python SDK)
- **Agent**: Claude Code, Codex, or OpenCode CLI subprocess (multi-provider registry)
- **GitHub auth**: GH_TOKEN PAT *or* GitHub App (app_id + private key path)
- **Agent slug format**: `agent:provider/model@effort` (e.g. `claude-code:anthropic/claude-sonnet-4-6@high`) — stored split as 3 columns in `runs`
- **Tests**: pytest (80% coverage floor), ruff, mypy strict, bandit
- **Deployment**: Docker (`Dockerfile` + `entrypoint.sh`), image published to GHCR via `publish.yml`

## Key Domain Terms

See `CONTEXT.md` for the full glossary. The critical ones:

- **Harness** — Labro itself; not smart
- **Task Source** — pluggable module that finds work (polled, not push-triggered)
- **Picker** — iterates the priority list, returns first non-None task
- **Permitted Actions** — what the agent may do (enforced at prompt level in M1)
- **Run** — one cycle: pick task → build prompt → invoke agent → log result

## Project Layout

```
src/labro/
  cli.py              # entry point (argparse)
  models.py           # Task, AgentConfig, ExecutionRecord
  picker.py           # priority-stack evaluator
  prompt_builder.py   # 4-section prompt constructor
  runner.py           # live run loop (lock → budget → pick → repo → agent → post-run)
  store.py            # SQLite (WAL): runs, project_locks, items_touched
  logger.py           # structured run logging
  repo.py             # repo preparation (clone/reset/checkout)
  post_run.py         # label transitions, items_touched writes
  assignee.py         # assignee resolution helpers
  config/             # schema.py (Pydantic), loader.py
  task_sources/       # base.py, gh_label.py, gh_author.py, proactive_improvement.py, gh_dependabot_alert.py
  agents/             # base.py, claude_code.py, codex.py, opencode.py, registry.py, _schema.py, _subprocess.py
tests/
docs/                 # PRD, ARCHITECTURE, ROADMAP, ADRs
```

## Commands

```bash
uv run pytest                          # run tests
uv run ruff check .                    # lint
uv run ruff format .                   # format (pre-commit hook enforces this — run before committing)
uv run mypy src/                       # type-check
uv run bandit -r src/                  # security lint
labro run <project> --dry-run          # dry-run
labro run <project>                    # live run
labro gen-crontab                      # emit crontab entries for all projects
docker build -t labro .                # build container image (VERSION defaults to SNAPSHOT)
```

**Before every commit:** run `uv run ruff format .` — the pre-commit hook will reformat and abort
if you skip it, requiring a second commit attempt.

## Sample Live Database

A copy of the live runs database is always available for dashboard development and testing:

```bash
# Fetch the current db URL from the manifest, then download it
curl -s https://labro.rossarnold.uk/manifest.json | python3 -c "import sys,json; print('https://labro.rossarnold.uk/' + json.load(sys.stdin)['db_filename'])" | xargs curl -fL -o /tmp/labro-sample.db
```

The manifest at `https://labro.rossarnold.uk/manifest.json` contains a `db_filename` field (e.g. `db/labro-184682a1c74c86a7.db`); prepend the base URL to get the download link. The hash in the filename rotates when the DB is republished.

## Hard Rules

- `bandit` B602 (`shell=True`) must **not** be skipped — subprocess calls use list form
- mypy runs in strict mode; no `# type: ignore` without a comment explaining why
- Config resolution order: label rule → task source → project → defaults

## Release Process

1. **Propose** — draft the changelog entries (features, fixes, breaking changes; user-facing, not commit-log) and propose a new version number (semver). Wait for user confirmation before making any changes.
2. **Changelog** — add a `## vX.Y.Z — YYYY-MM-DD` heading to `CHANGELOG.md` with the confirmed entries.
3. **Bump version** — update `version =` in `pyproject.toml` under `[project]`.
4. **Commit** — stage `CHANGELOG.md`, `pyproject.toml`, and `uv.lock` (version bump updates the lock file), then commit using the form `Release vX.Y.Z: <one-line summary>` (not a generic `chore:` prefix).
5. **Tag** — `git tag vX.Y.Z` on the release commit, then push the tag: `git push origin vX.Y.Z`.
6. **Docker image** — `publish.yml` triggers on the version-tag push (`v*.*.*`), publishing the versioned tag and `:latest` to GHCR; confirm the image built successfully after pushing the tag.

## Current Milestone

- **M1–M5 complete** — dry-run, config, task sources, prompt builder, agent invocation, SQLite store, post-run label transitions, Docker deployment, operator CLI.
- **M7 complete** — `proactive-improvement` task source: harness creates issue, randomly selected perspective from `perspectives.toml` injected as 5th prompt section, `chosen_perspective` column in `runs` table. M6 (`grafana-alerts`) skipped for now.
- **Recently shipped** — multi-provider agent registry (CodexAgent, OpenCodeAgent), GitHub App auth, perspectives feature (42 perspectives across 9 groups), `gh-dependabot-alert` task source.
- **Next** — M6: `grafana-alerts` task source, or M8: daily digest.
