#!/bin/sh
set -eu
cd "$(dirname "$0")"
# Prevent overlapping cron executions on Linux.
if command -v flock >/dev/null 2>&1; then
    exec flock -n .hira-alert.lock ./.venv/bin/python hira_alert.py
fi
exec ./.venv/bin/python hira_alert.py
