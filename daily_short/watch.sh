#!/bin/bash
# Intraday decision-line alerts (cron every 5 min, 09:00-16:55 ET Mon-Fri; watch.py exits outside 09:30-16:05).
# usage: watch.sh [--dry-run]
set -uo pipefail
export PATH=/Users/yuwang/.nvm/versions/node/v24.16.0/bin:/Users/yuwang/.local/bin:/opt/homebrew/bin:/usr/bin:/bin:$PATH
cd /Users/yuwang/.openclaw/workspace-claw-short/daily_short || exit 1
exec python3 watch.py "$@"
