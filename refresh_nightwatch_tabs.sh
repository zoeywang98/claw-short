#!/bin/bash
# Hourly refresh of the two Nightwatch dealer-heatmap tabs (GEX/VEX) to stop
# their long-lived-tab memory/CPU growth (see autocommit.log sibling diagnosis
# 2026-10-06: PID left open 14h hit 10.5GB footprint / 79% CPU).
# Matches any Chrome tab whose URL contains one of the two hash fragments
# and reloads it in place (keeps the tab, just resets its JS/DOM state).

LOG="/Users/yuwang/.openclaw/workspace-claw-short/refresh_nightwatch_tabs.log"

result=$(osascript <<'EOF'
tell application "Google Chrome"
	set n to 0
	repeat with w in windows
		repeat with t in tabs of w
			set u to URL of t
			if u contains "yehangshe.com/app/dealer-heatmap#nw-job-gex" or u contains "yehangshe.com/app/dealer-heatmap#nw-job-vex" then
				reload t
				set n to n + 1
			end if
		end repeat
	end repeat
	return n
end tell
EOF
)

echo "$(date '+%F %T %Z') refreshed ${result:-0} nightwatch tab(s)" >> "$LOG"
