# Compare holding.py (10-session lookback) with full sequencing from 10/16, for today 11/27 (synthetic brief = 11/25 bars + 11/27 close).
import json, os, re, sys
sys.path.insert(0, '/Users/yuwang/.openclaw/workspace-claw-short/daily_short')
import holding as Hd
WS = '/Users/yuwang/.openclaw/workspace-claw-short'; LOGS = f'{WS}/daily_short/logs'
X = json.load(open(f'{WS}/analysis_data/backtest-2026-10-18/v3_live/closes_2026-11-27.json'))
SCANS = sorted(d for d in os.listdir(LOGS) if re.fullmatch(r'\d{4}-\d{2}-\d{2}', d) and d >= '2026-10-16')
TODAY = '2026-11-27'
for T in sorted(X):
    b = json.load(open(f'{WS}/analysis_data/2026-11-25/{T}.json')) if os.path.exists(f'{WS}/analysis_data/2026-11-25/{T}.json') else None
    if not b: continue
    bars = [x for x in b['price']['last_22_bars']] + [[TODAY, None, None, None, X[T][TODAY], None]]
    cur = Hd.holding_state(TODAY, T, {'price': {'last_22_bars': bars}})
    # full sequencing: every post-close scan from 10/16, closes from the 1Y file
    days = sorted(d for d in X[T] if '2026-10-16' <= d <= TODAY)
    act = None
    for d in days[:-1]:
        if act:
            held = days.index(d) - days.index(act['entry_date'])
            if X[T][d] > act['stop'] or held >= 10: act = None
        if not act and d in SCANS:
            act = Hd._entry(d, '', T)
    full = None
    if act:
        held = days.index(TODAY) - days.index(act['entry_date'])
        st = '收盘站回' if X[T][TODAY] > act['stop'] else ('满10天' if held >= 10 else '持有中')
        full = (act['entry_date'][5:], act['stop'], held, st)
    c = (cur['entry_date'][5:], cur['stop'], cur['days_held'], cur['status'][:6]) if cur else None
    flag = '' if (c and full and c[:2] == full[:2]) or (c is None and full is None) else '  <-- differs'
    print(f"{T:5s} close {X[T][TODAY]:8.2f} | holding.py {c} | full {full}{flag}")
