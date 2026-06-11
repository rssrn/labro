# Quickstart

## Docker (recommended for production)

The `Dockerfile` bundles everything Labro needs: Python 3.12, the `gh` CLI, and the `claude` and `opencode` CLIs.

> **💡 Tip for Claude subscribers:** from June 2026, Pro/Max/Team/Enterprise plans include a [monthly pool of headless Agent SDK credits](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan) that expire unused. Labro gives you a concrete, low-risk way to put them to work on your own repos.

### Prerequisites

- **[Docker](https://docs.docker.com/get-docker/)** (or a compatible runtime such as Podman)
- **GitHub access** — either a **GitHub App** (recommended; bot identity) or a **PAT** (`GH_TOKEN`). See [GitHub Token Setup](docs/DEPLOYMENT.md#github-token-setup) for the full setup guide.
- **An agent credential** for live runs (not needed for `--dry-run`) — pick one based on which provider you plan to use:
  - **`CLAUDE_CODE_OAUTH_TOKEN`** — OAuth token for Claude Code (Pro/Max subscription). Generate once with `claude setup-token` on your dev machine.
  - **`OPENAI_API_KEY`** — API key for OpenAI Codex (`codex:openai/...` models).
  - **`OPENCODE_*` / provider key** — OpenCode supports any model on [models.dev](https://models.dev) (OpenRouter, Anthropic, Mistral, and more); see the [Model Selection Guide](docs/MODEL-SELECTION.md) for per-provider env vars.

  See [Deployment Guide](docs/DEPLOYMENT.md#agent-credentials) for the full list of supported env vars and precedence rules.

### 1. Clone and build

```bash
git clone https://github.com/rssrn/labro.git
cd labro
docker build --target base -t labro:latest .
```

> **Build targets:** `--target base` (production) omits the test suite and dev extras. Omit `--target` for the `dev` stage, which includes `tests/` — useful for CI and contributors. `labro:latest` is the production tag by convention.

**ARM64 / Oracle Cloud Ampere A1:** the image is arch-aware. Build natively on the instance, or cross-build from an amd64 host with:

```bash
docker buildx build --target base --platform linux/arm64 -t labro:arm64 .
```

### 2. Write a minimal `labro.toml`

```toml
[defaults]
model = "claude-code:anthropic/claude-sonnet-4-6"   # or an array for fallback: ["slug1", "slug2"]

[[projects]]
name       = "my-project"
repo       = "my-org/my-repo"
cron       = "0 * * * *"             # hourly; consumed by `labro gen-crontab` for scheduling

[[projects.task_sources]]
type = "gh-label"

[[projects.task_sources.label_rules]]
label             = "ai-dev"
done_label        = "ai-dev-done"
permitted_actions = ["comment_on_issue", "open_pr"]
```

The `cron` field tells `labro gen-crontab` how often to schedule each project. The container does not schedule itself — that's covered at the end of this section.

### 3. Create the labels and a test issue

Create the labels Labro expects in your repo:

```bash
docker run --rm \
  -e GH_TOKEN=<your-github-token> \
  -v "$PWD/labro.toml:/data/labro.toml:ro" \
  labro:latest init
```

This runs `gh label create --force` for every label in `labro.toml` (idempotent — safe to re-run).

Then open a real issue in `my-org/my-repo` and apply the `ai-dev` label to it. Labro picks tasks from live GitHub issues — without a labelled issue, the picker finds nothing and later steps will show "no task found."

### 4. Pre-flight check

Run `labro check` to validate your config, environment variables, and GitHub token connectivity:

```bash
docker run --rm \
  -e GH_TOKEN=<your-github-token> \
  -e <YOUR_AGENT_CREDENTIAL>=<value> \
  -v "$PWD/labro.toml:/data/labro.toml:ro" \
  labro:latest check
```

Replace `<YOUR_AGENT_CREDENTIAL>` with whichever var your provider uses (e.g. `CLAUDE_CODE_OAUTH_TOKEN`, `OPENAI_API_KEY`). Each output line is prefixed with `OK  `, `WARN`, or `FAIL` — fix any `FAIL` items before continuing.

### 5. Dry-run

Verify Labro resolves the test issue, builds the full prompt, and selects the right agent — no tokens spent, no writes, no side effects:

```bash
docker run --rm \
  -e GH_TOKEN=<your-github-token> \
  -v "$PWD/labro.toml:/data/labro.toml:ro" \
  labro:latest run my-project --dry-run
```

You should see the resolved task, agent config, and four-section prompt printed to stdout.

### 6. Validate your agent CLI

Before the first live run, confirm the agent CLI authenticates correctly inside the container. Example for Claude Code:

```bash
docker run --rm \
  --entrypoint sh \
  -e CLAUDE_CODE_OAUTH_TOKEN=<your-token> \
  labro:latest \
  -c 'echo "hello" | claude -p --output-format json'
```

The response should contain top-level `type`, `is_error`, and `result` fields. If it fails with an auth error requiring interactive login, resolve the container auth strategy before proceeding.

For Codex or OpenCode validation steps, see [Deployment Guide — Agent Credentials](docs/DEPLOYMENT.md#agent-credentials).

### 7. Live run

Run Labro against the test issue:

```bash
docker run --rm \
  -e GH_TOKEN=<your-github-token> \
  -e <YOUR_AGENT_CREDENTIAL>=<value> \
  -v "$PWD/labro.toml:/data/labro.toml:ro" \
  -v labro-data:/data \
  labro:latest run my-project
```

The `-v labro-data:/data` named volume persists `labro.db` (the run audit trail) across invocations. Labro will pick the test issue, invoke the agent, post a comment or open a PR, and transition the label from `ai-dev` to `ai-dev-done`.

**Next step — scheduling:** a one-shot `docker run` is enough for testing, but production use means running on a schedule. See the [Deployment Guide](docs/DEPLOYMENT.md) for GitHub Actions cron, a dedicated server with crond, and config-repo patterns.

---

## Local Python (recommended for development)

Use this path if you want to contribute, run the test suite, or iterate quickly without rebuilding the image.

### Prerequisites

- **Python 3.12+**
- **[uv](https://docs.astral.sh/uv/)** — fast Python package manager (`pip install uv` or see the uv docs)
- **[gh](https://cli.github.com/)** — GitHub CLI, authenticated (`gh auth login`)

### 1. Clone and create the virtual environment

```bash
git clone https://github.com/rssrn/labro.git
cd labro
uv venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
```

### 2. Install dependencies

```bash
uv pip install -e '.[dev]'
```

This installs Labro in editable mode along with all dev tools: ruff, mypy, bandit, pytest, pip-audit, and pre-commit.

### 3. Install pre-commit hooks

```bash
pre-commit install
```

Hooks run automatically on `git commit` (ruff, mypy-strict, bandit, shellcheck, check-toml, pytest) and on `git push` (pip-audit).

### 4. Run the test suite

```bash
pytest
```

### 5. First dry-run

Create a `labro.toml` as shown in the Docker quickstart above, then:

```bash
export GH_TOKEN=<your-github-token>
labro run my-project --dry-run
```

Labro will print the resolved task, agent config, and full four-section prompt to stdout.
