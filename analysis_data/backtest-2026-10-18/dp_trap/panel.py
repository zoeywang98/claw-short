#!/usr/bin/env python3
"""Daily panel per ticker: close + DP 2D / 1W / 1M centroid_top8 recomputed from per-day UW price-levels
(same aggregation as uw_short_fetch layers.py: windows = last 1/2/5/21 trading days, top-8 dark levels weighted)."""
import json, os, glob, sys
sys.path.insert(0, '/Users/yuwang/.openclaw/workspace-claw-short/uw_short_fetch')
from uwsf.layers import level_stats, _levels
from uwsf.watchlist import WATCHLIST, tickers_of
WS = '/Users/yuwang/.openclaw/workspace-claw-short'
WL = tickers_of(WATCHLIST)
prices = json.load(open(f'{WS}/analysis_data/backtest-2026-10-18/prices.json'))
# extend closes with the 10/26 briefs' last_22_bars
for T in WL:
    b = json.load(open(f'{WS}/analysis_data/2026-10-26/{T}.json'))
    for d, o, h, l, c, v in b['price']['last_22_bars']:
        old = prices[T].get(d)
        if old and abs(old[3] - c) / c > 0.002:
            print('price mismatch', T, d, old[3], c)
        prices[T][d] = [o, h, l, c]
days = sorted(set(d for T in WL for d in prices[T]))
by_day = {T: {} for T in WL}
for T in WL:
    for f in glob.glob(f'/private/tmp/bt_trap/dp_raw/{T}/*.json'):
        d = os.path.basename(f)[:-5]
        body = json.load(open(f))['body']
        by_day[T][d] = _levels(body.get('data') if isinstance(body, dict) else body)
    for f in glob.glob(f'{WS}/uw_short_fetch/cache/{T}/darkpool_levels_*.json'):
        d = os.path.basename(f).split('_')[2]
        body = json.load(open(f))['body']
        lv = _levels(body.get('data') if isinstance(body, dict) else body)
        if lv: by_day[T][d] = lv
    pdd = json.load(open(f'{WS}/analysis_data/2026-10-26/{T}.json'))['darkpool_levels']['per_day']
    for d, x in pdd.items():
        if d not in by_day[T]:
            lv = x['levels']; lv = lv['rows'] if isinstance(lv, dict) else lv
            by_day[T][d] = {p: [dk, rg] for p, dk, rg in lv}
def window(T, i, n):
    agg = {}
    wd = days[max(0, i - n + 1): i + 1]
    if len(wd) < n or any(d not in by_day[T] for d in wd): return None
    for d in wd:
        for p, v in by_day[T][d].items():
            a = agg.setdefault(p, [0.0, 0.0]); a[0] += v[0]; a[1] += v[1]
    return level_stats(agg)['centroid_top8']
panel = {}
for T in WL:
    rows = []
    for i, d in enumerate(days):
        if d not in prices[T]: continue
        o, h, l, c = prices[T][d]
        rows.append({'date': d, 'open': o, 'high': h, 'low': l, 'close': c,
                     'c1D': window(T, i, 1), 'c2D': window(T, i, 2), 'c1W': window(T, i, 5), 'c1M': window(T, i, 21)})
    panel[T] = rows
json.dump({'days': days, 'panel': panel}, open('/Users/yuwang/.openclaw/workspace-claw-short/analysis_data/backtest-2026-10-18/dp_trap/panel.json', 'w'))
# cross-check vs the briefs' own windows on scan dates
diffs = []
for D in sorted(os.listdir(f'{WS}/analysis_data')):
    if len(D) != 10 or not D.startswith('2026-'): continue
    for T in WL:
        f = f'{WS}/analysis_data/{D}/{T}.json'
        if not os.path.exists(f): continue
        w = (json.load(open(f)).get('darkpool_levels') or {}).get('windows') or {}
        for k in ('2D', '1W'):
            bv = (w.get(k) or {}).get('centroid_top8')
            mv = next((r[f'c{k}'] for r in panel[T] if r['date'] == D), None)
            if bv and mv: diffs.append((abs(bv - mv) / bv, D, T, k, bv, mv))
diffs.sort(reverse=True)
print('days', days[0], days[-1], len(days), '| crosscheck n', len(diffs), 'max', diffs[:5], '| >0.5%:', sum(1 for x in diffs if x[0] > 0.005))
