# Labro — CLAUDE.md

## What This Is

Labro is a self-hosted harness that runs Claude Code as a subprocess to perform autonomous maintenance on GitHub repos (triage issues, review PRs, investigate alerts). The harness is deliberately simple — deterministic, auditable orchestration. The agent is smart; Labro just selects a task, builds a prompt, and records the result.

## Tech Stack

- **Language**: Python 3.12+, managed with `uv`
- **CLI**: argparse — `run`, `gen-crontab`, `init`, `check`, `review`, `list-locks`, `unlock`, `publish-db`, `collect-signals`
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
  cli.py              # entry point (argparse) + the live run loop
  models.py           # Task, AgentConfig, ExecutionRecord
  picker.py           # priority-stack evaluator
  prompt_builder.py   # 4-section prompt constructor
  store.py            # SQLite (WAL): runs, project_locks, items_touched
  logger.py           # structured run logging
  repo.py             # repo preparation (clone/reset/checkout)
  post_run.py         # label transitions, items_touched writes
  github_app.py       # GitHub App auth (installation token minting)
  metrics.py          # Prometheus Pushgateway emission
  r2.py               # Cloudflare R2 upload (publish-db)
  signals.py          # signal collection (collect-signals)
  config/             # schema.py (Pydantic), loader.py
  task_sources/       # base.py, gh_label.py, gh_author.py, proactive_improvement.py, gh_dependabot_alert.py
  agents/             # base.py, claude_code.py, codex.py, opencode.py, registry.py, _schema.py, _subprocess.py
dashboard/            # React + Vite metrics SPA (sql.js reads the published snapshot)
perspectives.toml     # 42 prompt lenses for proactive-improvement runs
tests/
docs/                 # PRD, ARCHITECTURE, ROADMAP, DASHBOARD, DEPLOYMENT, OPERATIONS, ADRs
```

There is no `runner.py`. The live run loop (lock → budget → pick → repo → agent →
post-run) is `_cmd_run_live` in `cli.py`; agent invocation lives in `agents/`. The
`runner.py` re-export shim was removed in #35.

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
labro check                            # validate labro.toml
labro list-locks                       # show held project locks
labro unlock <project>                 # release a stuck lock
labro publish-db                       # snapshot the runs DB and upload to R2
docker build -t labro .                # build container image (VERSION defaults to SNAPSHOT)
```

Dashboard (`dashboard/`, Node pinned by `.nvmrc`):

```bash
cd dashboard && nvm use                # switch to the pinned Node major
npm ci                                 # install (warns via `engines` if Node is too old)
npm test                               # vitest (accessibility suite)
npm run build                          # tsc -b && vite build
npm run dev                            # dev server, proxies live R2 data
npm run preview                        # serve the production build (same proxy)
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

## Workflows in This Repo

| Workflow | Trigger | What it does |
|---|---|---|
| `ci-python.yml` | PRs and pushes to `main`, `paths-ignore: dashboard/**` | ruff, mypy, bandit, pytest. Reports as the `ci` check. |
| `ci-dashboard.yml` | PRs and pushes to `main`, `paths: dashboard/**` | `npm ci` + vitest + `tsc -b && vite build` on Node 22. Reports as the `build` check. |
| `publish.yml` | Push of a `v*.*.*` tag | Builds the image, pushes the versioned tag and `:latest` to GHCR, then fires `repository_dispatch: labro-release` at `labro-rssrn`. |
| `dashboard-dispatch.yml` | Push to `main` touching `dashboard/**` | Fires `repository_dispatch: dashboard-publish` at `labro-rssrn`, which rebuilds and republishes the SPA to R2. |

Note the path filters are directory-based: *any* file under `dashboard/` triggers the
dashboard workflows and a live republish, including non-build files like `.nvmrc`.

## Config Repo — `labro-rssrn` (`/home/ross/src/labro-rssrn`)

The private config repo holds `labro.toml` and four GitHub Actions workflows that manage the live deployment on the homelab server. All persistent state lives under `/opt/labro/data/` on the host (mounted to `/data` inside the container).

### Workflows

| Workflow | Trigger | What it does |
|---|---|---|
| `sync-config.yml` | Push to `labro.toml`, or manual | SCPs `labro.toml` to `/opt/labro/data/labro.toml` and regenerates `/etc/cron.d/labro` inside the running container. No restart needed — labro reads config fresh each cron run. |
| `upgrade-image.yml` | `repository_dispatch: labro-release` (fired by `publish.yml` on version tag), or manual | Pulls `ghcr.io/rssrn/labro:latest`, drains in-flight runs, recreates the container with fresh secrets. This is the normal upgrade path after a release. |
| `labro-restart.yml` | Manual only | Same drain + recreate as above but does **not** pull a new image. Use after rotating a secret or recovering from a hung state. |
| `dashboard-publish.yml` | `repository_dispatch: dashboard-publish` (fired by `dashboard-dispatch.yml` in `rssrn/labro` on any push to `main` touching `dashboard/**`), or manual | Builds the React SPA from `rssrn/labro` and uploads it to R2 with `--no-delete` (preserves `/db/` objects and `manifest.json` written by `labro publish-db`). |

### Container deployment

The container is managed by Docker Compose, not a raw `docker run`. The compose file
lives at `deploy/docker-compose.yml` in `labro-rssrn`; `upgrade-image.yml` and
`labro-restart.yml` render `deploy/.env` from repo secrets, rsync `deploy/` to
`/home/deploy/labro/` on the host, then `docker compose up -d --force-recreate` there.

Host layout:

| Path | What |
|---|---|
| `/home/deploy/labro/docker-compose.yml` | compose file (rsynced, `--delete`) |
| `/home/deploy/labro/.env` | secrets (rendered by the workflows) |
| `/opt/labro/data/` | persistent state, mounted to `/data` — outside the rsync |

Service definition: image `ghcr.io/rssrn/labro:latest`, `restart: unless-stopped`,
`/opt/labro/data:/data`, the external `monitoring` network (for `pushgateway:9091`),
a healthcheck asserting PID 1 is `cron` and `/etc/cron.d/labro` exists, json-file
logging capped at 3×10m, and `deploy.resources.limits.cpus: "1.5"` — a blast-radius
cap on the 2-vCPU host, added after rssrn/labro#58.

**Editing the compose file does not deploy it.** No workflow triggers on `deploy/**`
(`sync-config.yml` fires only on `labro.toml`), so run `labro-restart.yml` manually
to pick up compose changes.

### Secrets (stored in `labro-rssrn` repo settings)
- `TAILSCALE_AUTHKEY`, `DEPLOY_HOST` — SSH access via Tailscale
- `GH_APP_PRIVATE_KEY_BASE64` — GitHub App private key
- `CLAUDE_CODE_OAUTH_TOKEN`, `OPENROUTER_API_KEY`, `CODEX_API_KEY`, `CODEX_AUTH_JSON_BASE64` — agent credentials
- `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_ACCOUNT_ID`, `R2_BUCKET` — Cloudflare R2
- `PUSHGATEWAY_URL` — Prometheus Pushgateway (e.g. `http://pushgateway:9091`)
- `LABRO_READ_TOKEN` — read token for `rssrn/labro` (used by `dashboard-publish.yml`)
- `ANALYTICS_SNIPPET_HTML` *(optional)* — raw HTML injected into the dashboard's `<!-- ANALYTICS_SNIPPET -->` placeholder (e.g. a Umami/Plausible/GA script tag). Unset by default — public builds ship with no tracking.
- `CONFIG_REPO_DISPATCH_TOKEN` — PAT used by `labro`'s `publish.yml` and `dashboard-dispatch.yml` to fire `repository_dispatch` events into this repo

## Current Milestone

- **M1–M5 complete** — dry-run, config, task sources, prompt builder, agent invocation, SQLite store, post-run label transitions, Docker deployment, operator CLI.
- **M7 complete** — `proactive-improvement` task source: harness creates issue, randomly selected perspective from `perspectives.toml` injected as 5th prompt section, `chosen_perspective` column in `runs` table. M6 (`grafana-alerts`) skipped for now.
- **Recently shipped** — multi-provider agent registry (CodexAgent, OpenCodeAgent), GitHub App auth, perspectives feature (42 perspectives in a flat `[perspectives.<name>]` namespace), `gh-dependabot-alert` task source, metrics dashboard.
- **Next** — M6: `grafana-alerts` task source, or M8: daily digest.
- **Doc drift warning** — ARCHITECTURE.md, PRD.md, ROADMAP.md and CONTEXT.md still describe
  `grafana-alerts` and the Slack digest (`digest.py`, `labro digest`, a `digests` table) as if
  shipped. Neither exists in `src/labro/` yet — treat those sections as aspirational until M6/M8
  land, and correct them then rather than trusting them now.
