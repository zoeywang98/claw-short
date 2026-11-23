#!/bin/bash
# Nightly save of the UW site's dark pool price levels into uw_short_fetch/history/dp_levels_site
# (ZZ 2026-11-22 "这个你只要每天跑，保存在本地，就可以了吧，不用依赖api"; uw_short_fetch/site_capture.py).
# Automation "claw-short 暗池网站存档", weekdays 20:30 ET: after-hours trading ends 20:00, so the site's tape is final.
# --backfill 5 re-saves the last 6 sessions, so a missed night heals itself. A DICloak / API difference @ZZ.
export PATH=/Users/yuwang/.nvm/versions/node/v24.16.0/bin:/Users/yuwang/.local/bin:/opt/homebrew/bin:/usr/bin:/bin:$PATH
cd /Users/yuwang/.openclaw/workspace-claw-short/uw_short_fetch || exit 1
LOG=/Users/yuwang/.openclaw/workspace-claw-short/daily_short/logs/site_capture
mkdir -p "$LOG"
python3 site_capture.py --backfill 5 "$@" 2>&1 | tee -a "$LOG/$(TZ=America/New_York date +%F).log"
exit "${PIPESTATUS[0]}"
