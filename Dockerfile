# Labro container image — Python 3.12, gh CLI, and pinned claude CLI.
#
# The claude CLI is pinned to a specific version to prevent silent
# response-shape drift (ARCHITECTURE §8, line 1071).
#
# Build targets:
#   Production image (no tests):
#     docker build --target base -t labro:latest .
#   Dev image (includes tests/ + dev extras; default target):
#     docker build -t labro:dev .
#
# Pass --build-arg VERSION=x.y.z to bake an accurate version label (CI does this
# automatically from the git tag). Omitting it defaults to VERSION=SNAPSHOT.
#
# Cross-build for arm64 (e.g. Oracle Cloud Ampere A1) from an amd64 host:
#   docker buildx build --platform linux/arm64 -t labro:arm64 .
#
# M1 validation gate (operator runs). Two auth routes are supported:
#
#   Option A — Claude subscription (Pro/Max; recommended; bills subscription credit):
#     Generate a token once on your dev machine with `claude setup-token`, then:
#     docker run --rm --entrypoint sh \
#       -e CLAUDE_CODE_OAUTH_TOKEN=<token> labro:latest \
#       -c 'echo "hello" | claude -p --output-format json'
#
#   Option B — Anthropic API key (untested; bills API account):
#     docker run --rm --entrypoint sh \
#       -e ANTHROPIC_API_KEY=<key> labro:latest \
#       -c 'echo "hello" | claude -p --output-format json'
#
#   NOTE: if both vars are set, ANTHROPIC_API_KEY takes precedence.
#
# @author Claude Sonnet 4.6 Anthropic

ARG PYTHON_VERSION=3.12
ARG DEBIAN_RELEASE=bookworm
ARG GH_VERSION=2.72.0
ARG CLAUDE_VERSION=2.1.152
ARG CODEX_VERSION=0.135.0
ARG OPENCODE_VERSION=1.15.13
ARG NODE_VERSION=22.15.0

# ── Base ──────────────────────────────────────────────────────────────────────
# python:3.12-slim-bookworm — Debian 12 slim variant.
# "slim" removes docs, locales, and build tools (~130 MB vs ~380 MB for full).
# Debian base is required: apt+dpkg for the gh .deb, glibc for npm native binaries.
# Alpine is explicitly avoided: musl libc breaks pre-built Node/claude binaries,
# NodeSource doesn't support Alpine, and dpkg is unavailable for gh install.
FROM python:${PYTHON_VERSION}-slim-${DEBIAN_RELEASE} AS base

# TARGETARCH is set automatically by `docker build` / `docker buildx build`
# to the target platform architecture (e.g. "amd64", "arm64").
# It is used below to select the correct gh CLI release binary.
ARG TARGETARCH
ARG GH_VERSION
ARG CLAUDE_VERSION
ARG CODEX_VERSION
ARG OPENCODE_VERSION
ARG NODE_VERSION

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    LABRO_CONFIG=/data/labro.toml \
    LABRO_PERSPECTIVES=/app/perspectives.toml

ARG VERSION=SNAPSHOT

LABEL org.opencontainers.image.title="labro" \
      org.opencontainers.image.description="Self-hosted harness for autonomous agent maintenance of GitHub repos" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.source="https://github.com/rssrn/labro" \
      org.opencontainers.image.licenses="MIT"

# ── System dependencies + gh CLI + Node.js ───────────────────────────────────
# Combined into one layer so apt lists are only fetched and cleaned once.
#
# git       — required by gh (declared dependency in the .deb)
# xz-utils  — required to extract the Node.js tarball (tar -xJ)
# gh        — installed from GitHub release .deb (arch-aware via TARGETARCH)
#             using `apt-get install` rather than `dpkg -i` so that any future
#             dependency additions in the .deb are resolved automatically
# Node.js   — downloaded from nodejs.org (official binary tarball, not NodeSource)
#             to avoid NodeSource repo setup overhead and extra apt dependencies;
#             amd64→x64 mapping required to match nodejs.org naming convention
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        cron \
        curl \
        git \
        sqlite3 \
        xz-utils \
    && GH_DEB="gh_${GH_VERSION}_linux_${TARGETARCH}.deb" \
    && curl -fsSL -o "/tmp/${GH_DEB}" \
       "https://github.com/cli/cli/releases/download/v${GH_VERSION}/${GH_DEB}" \
    && apt-get install -y --no-install-recommends "/tmp/${GH_DEB}" \
    && rm "/tmp/${GH_DEB}" \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && NODE_ARCH=$([ "$TARGETARCH" = "amd64" ] && echo "x64" || echo "$TARGETARCH") \
    && curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${NODE_ARCH}.tar.xz" \
       | tar -xJ -C /usr/local --strip-components=1

# ── claude CLI ────────────────────────────────────────────────────────────────
# Pinned via npm to avoid silent response-shape drift (ARCHITECTURE §8).
RUN npm install -g "@anthropic-ai/claude-code@${CLAUDE_VERSION}" \
    && npm cache clean --force

# ── codex CLI — standalone Rust binary from GitHub Releases ──────────────────
# The @openai/codex npm package is a JS shim that requires platform-specific
# optional deps at runtime; the musl binary from GitHub Releases is self-contained.
# Tag format is rust-v{VERSION}; archive contains a single binary named with the
# platform triple, so tar -xzO pipes it directly to the destination path.
RUN CODEX_ARCH=$([ "$TARGETARCH" = "amd64" ] && echo "x86_64" || echo "aarch64") \
    && curl -fsSL \
       "https://github.com/openai/codex/releases/download/rust-v${CODEX_VERSION}/codex-${CODEX_ARCH}-unknown-linux-musl.tar.gz" \
       | tar -xzO > /usr/local/bin/codex \
    && chmod +x /usr/local/bin/codex

# ── opencode CLI — standalone glibc binary from GitHub Releases ───────────────
# Tarball contains a single binary named "opencode" at the root.
# glibc variant used (matches Debian bookworm base; Alpine/musl not supported here).
RUN OPENCODE_ARCH=$([ "$TARGETARCH" = "amd64" ] && echo "x64" || echo "arm64") \
    && curl -fsSL \
       "https://github.com/anomalyco/opencode/releases/download/v${OPENCODE_VERSION}/opencode-linux-${OPENCODE_ARCH}.tar.gz" \
       | tar -xzO > /usr/local/bin/opencode \
    && chmod +x /usr/local/bin/opencode

# ── Git credential helper ─────────────────────────────────────────────────────
# Set gh as the global git credential provider so agent-invoked `git push` calls
# authenticate via GH_TOKEN / GitHub App token without per-call -c flags.
# This is image-wide config; the actual `gh auth git-credential` command only
# runs at the moment git needs credentials (not at build time).
RUN git config --global credential.helper '!gh auth git-credential'

# ── uv ────────────────────────────────────────────────────────────────────────
RUN pip install uv

# ── Application ───────────────────────────────────────────────────────────────
WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY src/ src/
COPY perspectives.toml ./
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

RUN uv venv /app/.venv \
    && uv pip install --python /app/.venv/bin/python -e .

ENV PATH="/app/.venv/bin:$PATH"

# ── Entrypoint ────────────────────────────────────────────────────────────────
# entrypoint.sh runs as PID 1 and supports two modes:
#   - Crond mode (no args): generates /etc/cron.d/labro and execs crond -f
#   - One-shot mode (with args): execs the given command directly (e.g. labro run <project>)
#
# Smoke test with --entrypoint sh:
#   docker run --rm --entrypoint sh labro:latest -c 'labro --help'
#
# See ARCHITECTURE.md §4 Container View and §5 entrypoint.sh and crontab generation.
ENTRYPOINT ["/app/entrypoint.sh"]

# ── Dev target ────────────────────────────────────────────────────────────────
# Extends the production image with tests/ and dev extras (pytest, ruff, mypy,
# bandit). This is the default build target so `docker build -t labro:dev .`
# produces a test-capable image without any extra flags.
# Production builds use: docker build --target base -t labro:latest .
FROM base AS dev

COPY tests/ tests/
RUN uv pip install --python /app/.venv/bin/python -e ".[dev]"
