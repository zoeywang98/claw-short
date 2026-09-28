#!/bin/bash
# Daily post-close short scan, one ticker at a time:
#   1. market layer once (all tickers, greek-exposure only -> watchlist breaker board, calendar, correlations)
#   2. fetch full data for every ticker, then add the whole-watchlist cross-section to the market brief
#   3. per ticker: brief -> bare `claude -p` analysis (analyze.py) -> post to Discord as claw-short
#   4. one summary post over all tickers (summarize.py)
#
# usage: run.sh [--dry-run] [--tickers LITE,COHR] [--date YYYY-MM-DD]
#   --dry-run   analyse but do not post to Discord (replies saved under logs/<D>/)
#   --date      re-analyse an already-fetched day: no fetching, no "today" guard
#               (uses runs/ from a per-ticker run of that day, else the old all-at-once data/<D>/)
set -uo pipefail

WS=/Users/yuwang/.openclaw/workspace-claw-short
FETCH=$WS/uw_short_fetch
HERE=$WS/daily_short
RUNS=$FETCH/runs
export PATH=/Users/yuwang/.nvm/versions/node/v24.16.0/bin:/Users/yuwang/.local/bin:/opt/homebrew/bin:/usr/bin:/bin:$PATH
# every per-ticker layer except greek-exposure: the market pass only needs each name's net gamma
MARKET_SKIP=darkpool-levels,darkpool,option-trades,gex-levels,short-interest,short-volume,short-data,lit-blocks,ohlc-daily,ohlc-5m,oi-change,option-contracts,oi-per-strike,options-volume,interpolated-iv,option-sentiment,unusualness,options-pulse,multi-leg,flow-per-strike,net-prem-ticks,greek-exposure-strike,offlit-levels,flow-alerts,spot-gex,contract-history,rr-skew,iv-rv

DRY=0; TICKERS=""; DATE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --tickers) TICKERS="$2"; shift ;;
    --date) DATE="$2"; shift ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
  shift
done
cd "$FETCH" || exit 1
WATCHLIST=$(python3 -c "from uwsf.watchlist import WATCHLIST, tickers_of; print(','.join(tickers_of(WATCHLIST)))")
TICKERS=${TICKERS:-$WATCHLIST}

usage_line() { sed -n 2p "$1" 2>/dev/null; }   # "UW usage: daily used=… · this run: N requests, M cache hits, Ts"

if [ -z "$DATE" ]; then
  TODAY=$(TZ=America/New_York date +%F)
  python3 fetch.py --quiet --tickers "$WATCHLIST" --skip "$MARKET_SKIP" --out "$RUNS/market"
  DATE=$(basename "$(dirname "$(ls -t "$RUNS"/market/*/run_summary.json | head -1)")")
  echo "market layer $DATE · $(usage_line "$RUNS/market/$DATE/run_log.txt")"
  if [ "$DATE" != "$TODAY" ]; then
    echo "NO_REPLY latest trading day $DATE != today $TODAY (holiday?) - skipped"
    exit 0
  fi
  python3 brief.py --date "$DATE" --data "$RUNS/market" --market-only || exit 1
  MARKET=$RUNS/market/$DATE/market_brief.json
  FRESH=1
else
  MARKET=$RUNS/market/$DATE/market_brief.json
  if [ ! -f "$MARKET" ]; then
    python3 brief.py --date "$DATE" --market-only || exit 1
    MARKET=$FETCH/data/$DATE/market_brief.json
  fi
  FRESH=0
fi

LOG=$HERE/logs/$DATE; mkdir -p "$LOG"
ok=0; fail=0; FAILED=""; STARTED=$(date +%s)
# fetch every ticker before any analysis, so each read sees the whole watchlist (SHORT_ENGINE §2 / §5.2)
if [ $FRESH -eq 1 ]; then
  for T in ${TICKERS//,/ }; do
    python3 fetch.py --quiet --tickers "$T" --date "$DATE" --out "$RUNS/tickers/$T" > "$LOG/$T.fetch.out" 2>&1
    echo "$T fetch · $(usage_line "$RUNS/tickers/$T/$DATE/run_log.txt")"
  done
fi
python3 brief.py --date "$DATE" --tickers "$TICKERS" --cross-section "$MARKET" > "$LOG/_cross_section.out" 2>&1 \
  && echo "cross-section · $(tail -1 "$LOG/_cross_section.out")" \
  || echo "⚠ cross-section failed (see logs/$DATE/_cross_section.out)"
for T in ${TICKERS//,/ }; do
  if [ -f "$RUNS/tickers/$T/$DATE/$T/snapshot.json" ]; then
    SRC=$RUNS/tickers/$T
  else
    SRC=$FETCH/data            # old all-at-once layout (manual --date runs on earlier days)
  fi
  if ! python3 brief.py --date "$DATE" --data "$SRC" --tickers "$T" --no-market > "$LOG/$T.brief.out" 2>&1; then
    fail=$((fail+1)); FAILED="$FAILED,$T"; echo "❌ $T brief (see logs/$DATE/$T.brief.out)"; continue
  fi
  if python3 "$HERE/analyze.py" --date "$DATE" --ticker "$T" --brief "$SRC/$DATE/$T/brief.json" \
       --market-brief "$MARKET" $( [ $DRY -eq 1 ] && echo --dry-run ) 2> "$LOG/$T.err"; then
    ok=$((ok+1)); echo "✅ $T"
  else
    fail=$((fail+1)); FAILED="$FAILED,$T"; echo "❌ $T (see logs/$DATE/$T.err)"
  fi
done
python3 "$HERE/summarize.py" --date "$DATE" --tickers "$TICKERS" --failed "${FAILED#,}" \
  --elapsed $(( $(date +%s) - STARTED )) $( [ $DRY -eq 1 ] && echo --dry-run ) > "$LOG/_summary.out" 2>&1 \
  && echo "✅ summary posted" || echo "❌ summary (see logs/$DATE/_summary.out)"
echo "short scan $DATE: $ok ok, $fail failed"
[ $fail -eq 0 ]
