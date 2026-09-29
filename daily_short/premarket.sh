#!/bin/bash
# Pre-open confirmation (08:45 ET, Mon-Fri): re-read the last scan's 👀 / ✅ names once today's OI is published.
# usage: premarket.sh [--dry-run] [--scan-date D] [--date D] [--tickers A,B] [--asof HH:MM]
set -uo pipefail
export PATH=/Users/yuwang/.nvm/versions/node/v24.16.0/bin:/Users/yuwang/.local/bin:/opt/homebrew/bin:/usr/bin:/bin:$PATH
cd /Users/yuwang/.openclaw/workspace-claw-short/daily_short || exit 1
exec python3 confirm.py "$@"
