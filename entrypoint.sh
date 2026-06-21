#!/bin/bash
set -euo pipefail

# Wire up codex auth.json from the data volume so headless token refresh persists
# across container recreations. The host file lives at /opt/labro/data/codex/auth.json
# (named without a leading dot for visibility); the codex CLI expects ~/.codex/auth.json.
if [ -f /data/codex/auth.json ]; then
    mkdir -p /root/.codex
    ln -sf /data/codex/auth.json /root/.codex/auth.json
elif [ -n "${CODEX_AUTH_JSON_BASE64:-}" ]; then
    mkdir -p /root/.codex
    echo "$CODEX_AUTH_JSON_BASE64" | base64 -d > /root/.codex/auth.json
    chmod 600 /root/.codex/auth.json
fi

# Export container env so crond jobs inherit secrets (GH_TOKEN, CLAUDE_CODE_OAUTH_TOKEN, etc.)
# LABRO_CONFIG is set here (not by the caller) so crond jobs find the config regardless of cwd.
LABRO_CONFIG="${LABRO_CONFIG:-/data/labro.toml}"
export LABRO_CONFIG
export -p > /etc/labro-env
chmod 600 /etc/labro-env

# On-demand mode (GitHub Actions / manual exec): pass args through to labro
if [ "$#" -gt 0 ]; then
    echo "$(labro --version) container starting up in on-demand mode"
    exec "$@"
fi

# Crond mode (VPS): generate crontab and start crond as PID 1
# Record startup in labro.log (not just stdout) so container restarts/upgrades
# are visible alongside run records. Match the Python logger's line format so
# the entries interleave cleanly: "<ts> INFO <name>: <message>".
startup_msg="$(labro --version) container starting up in cron mode"
echo "$startup_msg"
# Guard the append (mirrors cli.py, which only logs to file when the dir exists)
# so a missing /data volume can't abort startup under `set -e`.
log_path="${LABRO_LOG_PATH:-/data/labro.log}"
if [ -d "$(dirname "$log_path")" ]; then
    echo "$(date -u '+%Y-%m-%d %H:%M:%S,%3N') INFO entrypoint: $startup_msg" >> "$log_path"
    # Tail the log file to stdout so 'docker logs' shows labro output.
    # touch ensures the file exists before tail starts.
    touch "$log_path"
    tail -F "$log_path" &
fi
mkdir -p /var/log/labro
labro gen-crontab > /etc/cron.d/labro
chmod 644 /etc/cron.d/labro

exec cron -f
