#!/bin/bash
# Daily auto-commit + push of workspace-claw-short to github.com/zoeywang98/claw-short
cd /Users/yuwang/.openclaw/workspace-claw-short || exit 1
echo "=== $(date '+%F %T %Z') ==="
git add -A
if git diff --cached --quiet; then
  echo "no changes"
else
  git commit -q -m "auto: daily snapshot $(date +%F)" && git log --oneline -1
fi
git push 2>&1
