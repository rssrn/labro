# Labro — CLAUDE.md

## What This Is

Labro is a self-hosted harness that runs Claude Code as a subprocess to perform autonomous maintenance on GitHub repos (triage issues, review PRs, investigate alerts). The harness is deliberately dumb — deterministic, auditable orchestration. The agent is smart; Labro just selects a task, builds a prompt, and records the result.

## Tech Stack

- **Language**: Python 3.12+, managed with `uv`
- **CLI**: Typer (`labro run <project> --dry-run`)
- **Config**: TOML (`labro.toml`), validated with Pydantic 2
- **GitHub**: `gh` CLI subprocess (not a Python SDK)
- **Agent**: Claude Code CLI subprocess
- **Tests**: pytest (70% coverage floor), ruff, mypy strict, bandit

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
  cli.py              # entry point
  models.py           # Task, AgentConfig
  picker.py           # priority-stack evaluator
  prompt_builder.py   # 4-section prompt constructor
  config/             # schema.py (Pydantic), loader.py
  task_sources/       # base.py, gh_delegated.py
  agents/             # placeholder (M2+)
tests/
docs/                 # PRD, ARCHITECTURE, ROADMAP, ADRs
```

## Commands

```bash
uv run pytest                          # run tests
uv run ruff check .                    # lint
uv run mypy src/                       # type-check
labro run <project> --dry-run          # dry-run (M1 only mode)
```

## Hard Rules

- `bandit` B602 (`shell=True`) must **not** be skipped — subprocess calls use list form
- mypy runs in strict mode; no `# type: ignore` without a comment explaining why
- Config resolution order: label rule → task source → project → defaults

## Current Milestone

**M1 complete** — dry-run, config loading, gh-delegated task source, prompt builder.
**M2 in progress** — live agent invocation, lock management, SQLite logging, crond scheduling.
