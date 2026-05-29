#!/bin/bash
set -euo pipefail

# Export container env so crond jobs inherit secrets (GH_TOKEN, CLAUDE_CODE_OAUTH_TOKEN, etc.)
# LABRO_CONFIG is set here (not by the caller) so crond jobs find the config regardless of cwd.
LABRO_CONFIG="${LABRO_CONFIG:-/app/labro.toml}"
export LABRO_CONFIG
export -p > /etc/labro-env
chmod 600 /etc/labro-env

# One-shot mode (GitHub Actions / manual): pass args through to labro
if [ "$#" -gt 0 ]; then
    exec "$@"
fi

# Crond mode (VPS): generate crontab and start crond as PID 1
mkdir -p /var/log/labro
labro gen-crontab > /etc/cron.d/labro
chmod 644 /etc/cron.d/labro

exec cron -f
