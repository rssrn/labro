# Labro — Deployment Guide

This guide covers GitHub access configuration, Docker deployment patterns, and the recommended config-repo workflow.

## GitHub Token Setup

There are two ways to give Labro access to your GitHub repos. **GitHub App** (recommended) uses a proper bot identity; a **PAT** is simpler to set up but attaches activity to your personal account.

### Option A — GitHub App (recommended)

A GitHub App gives Labro a proper bot identity (`your-app[bot]`) with scoped permissions and no user account needed. Labro generates a short-lived installation token automatically at the start of each run — no `GH_TOKEN` env var required.

**1. Create the app:**

- Go to **GitHub → Settings → Developer settings → GitHub Apps → New GitHub App**
- **App name**: something unique like `labro-yourusername` (GitHub names are global)
- **Homepage URL**: your repo URL (required by GitHub, not used by Labro)
- **Webhook**: uncheck *Active* — Labro doesn't receive webhooks
- **Permissions** — set these under *Repository permissions*:

| Permission | Level | Why |
|---|---|---|
| Contents | Read & write | Push WIP branches |
| Dependabot alerts | Read-only | Fetch open security alerts (`gh-dependabot-alert` source) |
| Issues | Read & write | Comment, add/remove labels |
| Metadata | Read-only | Repo lookup (required by GitHub) |
| Pull requests | Read & write | Open PRs |

- **Identifying and authorizing users**: leave everything blank/unchecked — Labro uses installation tokens, not user OAuth
- **Where can this be installed**: *Only on this account*
- Click **Create GitHub App**

**2. Get your credentials:**

- Note the **App ID** shown on the app's settings page
- Scroll to the bottom and click **Generate a private key** — save the downloaded `.pem` file securely

**3. Install the app on your repos:**

- On the app settings page, click **Install App** → select your account → choose the repos Labro monitors

**4. Configure `labro.toml`:**

```toml
github_app_id   = 12345                    # your App ID
github_app_name = "labro-yourusername"     # your app slug (without [bot])

# Set claude_assignee to the bot's GitHub username
claude_assignee = "labro-yourusername[bot]"
```

**5. Pass the private key as an environment variable:**

The private key PEM goes in `GH_APP_PRIVATE_KEY` — not in `labro.toml`, which keeps secrets out of your config file.

```bash
export GH_APP_PRIVATE_KEY="$(cat labro-yourusername.pem)"
```

For Docker:

```bash
docker run --rm \
  -e GH_APP_PRIVATE_KEY="$(cat labro-yourusername.pem)" \
  -e CLAUDE_CODE_OAUTH_TOKEN=<your-token> \
  -v "$PWD/labro.toml:/data/labro.toml:ro" \
  labro:latest run my-project
```

> **Multi-line keys in env files:** GitHub App private keys are multi-line PEM. If you use a `.env` file or `--env-file`, you'll need to quote the key or use a secrets manager that handles multi-line values (GitHub Actions secrets, Docker secrets, and Vault all work natively).

### Option B — Personal Access Token (PAT)

`GH_TOKEN` must belong to an account that has **collaborator access** (or ownership) of every repo in your `labro.toml`. The token needs the following permissions:

| Permission | Level | Why |
|---|---|---|
| Contents | Read & write | Push branches for PRs |
| Dependabot alerts | Read-only | Fetch open security alerts (`gh-dependabot-alert` source) |
| Issues | Read & write | Comment on issues, add/remove labels |
| Metadata | Read-only | List issues, repo lookup (required by GitHub) |
| Pull requests | Read & write | Open PRs |

**Fine-grained PAT:** create it under the account that owns the repos. Fine-grained PATs can only access repos owned by the issuing account — select "Only select repositories" and add each repo explicitly.

**Classic PAT:** use `repo` scope. Simpler, but broader than necessary.

---

## Docker Deployment

### Deployment Modes

Labro supports two production deployment modes:

**GitHub Actions (recommended)** — run Labro as a scheduled workflow in your config repo. No VPS required. Each workflow invocation is a one-shot container run; the agent handles one task and exits. Use this pattern for low-frequency schedules (daily/hourly) or when you already have GitHub Actions available.

**VPS with crond (always-on)** — run Labro as a long-lived container on a server. The container generates a crontab at startup from `labro.toml` and runs `crond` as PID 1. Use this for sub-hourly schedules or when you want a persistent process.

> **Entrypoint behaviour:** the two modes are driven by whether you pass a command to `docker run`.
> - **No command** (VPS crond mode): `docker run labro:latest` — `entrypoint.sh` runs `labro gen-crontab`, writes `/etc/cron.d/labro`, and execs `crond -f` as PID 1.
> - **With a command** (one-shot / GitHub Actions): `docker run labro:latest labro run my-project` — the entrypoint skips cron entirely and execs the given command directly.
>
> No cron job is installed until the no-command path runs; the one-shot path never touches cron at all.
>
> **Local testing — persistent container, no cron:** pass `sleep infinity` as the command to keep the container alive without installing a crontab, then invoke runs manually with `docker exec`:
> ```bash
> docker run -d --name labro-test \
>   -e GH_TOKEN=<token> \
>   -e CLAUDE_CODE_OAUTH_TOKEN=<token> \
>   -v "$PWD/labro.toml:/data/labro.toml:ro" \
>   labro:latest sleep infinity
>
> docker exec labro-test labro run my-project --dry-run
> ```

### GHCR Image

Pre-built images are published to GHCR on every version tag. Both the versioned tag and `:latest` are pushed:

```
ghcr.io/rssrn/labro:<tag>
ghcr.io/rssrn/labro:latest
```

```bash
docker pull ghcr.io/rssrn/labro:latest
# or pin to a specific version:
docker pull ghcr.io/rssrn/labro:v0.7.0
```

### Bind-Mount Layout

The recommended layout uses a **single volume mount** — all persistent state lives under one host directory:

| Host path | Container path | Purpose |
|---|---|---|
| `/your/data/dir/` | `/data/` | Config, SQLite DB, logs, repos, `LABRO_DISABLED` flag |

Inside the mounted directory:

```
/your/data/dir/
  labro.toml        ← LABRO_CONFIG=/data/labro.toml
  labro.db          ← SQLite run records
  labro.log         ← structured run log
  repos/            ← LABRO_REPOS_DIR=/data/repos (per-run checkouts, deleted after each run)
  codex/
    auth.json       ← codex CLI auth (symlinked to ~/.codex/auth.json by entrypoint)
```

Set `LABRO_CONFIG` and `LABRO_REPOS_DIR` to point inside `/data`:

```bash
docker run \
  -e LABRO_CONFIG=/data/labro.toml \
  -e LABRO_REPOS_DIR=/data/repos \
  -v /your/data/dir:/data \
  ...
```

### GitHub Actions (One-Shot, Recommended)

Add this workflow to your config repo's `.github/workflows/`:

```yaml
# .github/workflows/labro-run.yml
on:
  schedule:
    - cron: '0 9 * * *'   # match the cron in your labro.toml
  workflow_dispatch:

jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run labro
        run: |
          docker run --rm \
            -e GH_TOKEN=${{ secrets.GH_TOKEN }} \
            -e CLAUDE_CODE_OAUTH_TOKEN=${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }} \
            -v $PWD/labro.toml:/data/labro.toml:ro \
            ghcr.io/rssrn/labro:v0.7.0 labro run my-project
```

### VPS with crond (Always-On)

Run Labro via `docker compose` rather than a bare `docker run` — it gives you declarative recreates (`up -d`) instead of manual `stop`/`rm`/`run`, which is what the config-repo workflows below rely on.

`docker-compose.yml` (see [`docs/config-repo-scaffold/docker-compose.yml`](config-repo-scaffold/docker-compose.yml) for a copy-pasteable version):

```yaml
services:
  labro:
    image: ghcr.io/rssrn/labro:latest
    container_name: labro
    restart: unless-stopped
    env_file: .env
    volumes:
      - ./data:/data
```

Place it at `/your/deploy/dir/docker-compose.yml`, with `/your/deploy/dir/.env` alongside it (at minimum):

```
LABRO_CONFIG=/data/labro.toml
LABRO_REPOS_DIR=/data/repos
GH_APP_PRIVATE_KEY_BASE64=<base64 -w 0 your-app.pem>
CLAUDE_CODE_OAUTH_TOKEN=<token>
```

Then, from `/your/deploy/dir`:

```bash
docker compose up -d
```

`entrypoint.sh` generates `/etc/cron.d/labro` from `labro.toml` and execs `crond -f`. Verify the crontab was generated correctly:

```bash
docker compose exec -T labro cat /etc/cron.d/labro
```

### Graceful Restart Procedure

When updating the config or rotating secrets, drain in-flight runs before restarting. Run these from `/your/deploy/dir` (where `docker-compose.yml` lives):

> **Scripting this over SSH:** `-T` only disables pseudo-TTY allocation — `docker compose exec` still attaches stdin to the exec'd process. Inside an SSH heredoc, that means the exec'd command silently consumes the rest of the script as its own input, and everything after it (including the actual `up -d --force-recreate`) never runs — while the step still exits 0. Add `< /dev/null` to every `exec` call below when running this non-interactively (e.g. from a GitHub Actions heredoc); the scaffold workflows already do this.

```bash
# 1. Signal no new runs
docker compose exec -T labro touch /data/LABRO_DISABLED

# 2. Wait for any run in progress to finish
while [ "$(docker compose exec -T labro sqlite3 /data/labro.db 'SELECT COUNT(*) FROM project_locks')" != "0" ]; do
  echo "waiting…"; sleep 5
done

# 3. Recreate (entrypoint regenerates crontab on start)
docker compose up -d --force-recreate

# 4. Re-enable
docker compose exec -T labro rm -f /data/LABRO_DISABLED
```

---

## Config Repo

The recommended production setup separates the harness (this repo) from your operator configuration. Keep your `labro.toml`, API keys, and deployment workflows in a **private config repo** — nothing sensitive ever touches the harness codebase.

**[rssrn/labro-rssrn](https://github.com/rssrn/labro-rssrn)** is a working example of this pattern — fork it or use it as a reference when setting up your own config repo.

### What Goes in the Config Repo

```
my-labro-config/
  labro.toml                        ← your operator config (checked in)
  docker-compose.yml                ← service definition (checked in)
  .gitignore                        ← excludes *.pem, *.key, .env
  .github/workflows/
    labro-deploy.yml                ← auto-triggered on labro.toml/docker-compose.yml changes
    labro-update.yml                ← manual: pull latest image and redeploy
    labro-restart.yml               ← manual: refresh secrets and restart
    dashboard-publish.yml           ← auto-triggered on dashboard/** changes; builds + uploads SPA to R2
```

`docker-compose.yml` and `labro.toml` are both synced to the server (to `/opt/labro/docker-compose.yml` and `/opt/labro/data/labro.toml` respectively); `.env` is written directly on the server by the workflows from GitHub repo secrets and never checked in.

Scaffold copies of all workflows plus `docker-compose.yml` are in [`docs/config-repo-scaffold/`](docs/config-repo-scaffold/). Copy them into your config repo and adjust the host paths and image name to match your setup:

```bash
cp docs/config-repo-scaffold/*.yml <your-config-repo>/.github/workflows/
cp docs/config-repo-scaffold/docker-compose.yml <your-config-repo>/docker-compose.yml
```

### How the Workflows Connect

The workflows SSH to your server (the scaffolds use [Tailscale](https://tailscale.com) for private networking, but any SSH-reachable host works) and manage the container lifecycle via `docker compose`:

| Workflow | Trigger | What it does |
|---|---|---|
| `labro-deploy.yml` | Push to `labro.toml` or `docker-compose.yml` | Copies config/compose file → drains → `docker compose up -d --force-recreate` |
| `labro-update.yml` | Manual | Writes fresh secrets → `docker compose pull` → drains → recreates container |
| `labro-restart.yml` | Manual | Writes fresh secrets → drains → `docker compose up -d --force-recreate` (same image) |
| `dashboard-publish.yml` | `dashboard-publish` dispatch or manual | Checks out labro repo → builds SPA → uploads assets to R2 |

All workflows write `/your/secrets/.env` on the server from GitHub repo secrets before recreating the container, so rotating any API key is just: update the secret in GitHub → run `labro-restart.yml`.

### GitHub Repo Secrets

| Secret | Notes |
|---|---|
| `DEPLOY_HOST` | `user@hostname` — your server's SSH address |
| `GH_APP_PRIVATE_KEY_BASE64` | `base64 -w 0 your-app.pem` |
| `CLAUDE_CODE_OAUTH_TOKEN` | If using claude-code agent |
| `OPENROUTER_API_KEY` | If using opencode with OpenRouter |
| `CODEX_API_KEY` | If using codex via OpenAI API billing |
| `CODEX_AUTH_JSON_BASE64` | If using codex via CLI subscription billing — `base64 -w 0 ~/.codex/auth.json`; bind-mounted so headless token refresh persists across container recreations |
| `R2_ACCESS_KEY_ID` | If `[dashboard] enabled = true` — used by `dashboard-publish.yml` to upload the SPA, and by the deploy workflows to write the VPS `.env` |
| `R2_SECRET_ACCESS_KEY` | If `[dashboard] enabled = true` |
| `R2_ACCOUNT_ID` | If `[dashboard] enabled = true` |
| `R2_BUCKET` | If `[dashboard] enabled = true` — bucket name used by both `dashboard-publish.yml` and `labro publish-db` |

### Codex CLI Auth in Containers

The codex CLI supports two auth modes:

- **`CODEX_API_KEY`** — OpenAI API key; pay-per-token. Pass it in the `.env` file.
- **`~/.codex/auth.json`** — CLI subscription billing (includes free credits tier); supports headless auto-refresh. Store the file contents as `CODEX_AUTH_JSON_BASE64` in GitHub secrets. The scaffold workflows decode it and write it to your data directory; `entrypoint.sh` symlinks it to `~/.codex/auth.json` so the codex CLI finds it and can refresh it in place.

  > If the auth.json tokens go stale (the container hasn't run in several weeks), run `codex auth login` locally, re-encode the refreshed file, update the GitHub secret, and trigger `labro-restart.yml`.

### Server Host Layout

```
/opt/labro/docker-compose.yml  ← synced by labro-deploy.yml
/opt/labro/.env                ← written by workflow; read by docker at run time (not mounted)
/opt/labro/data/                ← single volume mount (./data:/data in docker-compose.yml)
  labro.toml                ← LABRO_CONFIG=/data/labro.toml
  labro.db                  ← SQLite run records
  labro.log
  repos/                    ← LABRO_REPOS_DIR=/data/repos (per-run checkouts)
  codex/
    auth.json               ← symlinked to ~/.codex/auth.json by entrypoint
```
