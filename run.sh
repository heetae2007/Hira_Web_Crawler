#!/bin/sh
set -eu
cd "$(dirname "$0")"
# Linux에서는 cron 중복 실행을 막는다.
if command -v flock >/dev/null 2>&1; then
    exec flock -n .hira-alert.lock ./.venv/bin/python -m hira_alert
fi
exec ./.venv/bin/python -m hira_alert
