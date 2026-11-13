"""Per name-day DP features 7/16-11/11 for the 23-name list: day dark vs 1M avg, day POC, densest 1% band,
centroid_top8 for 1D/2D/1W/1M (same level_stats as the fetcher), OHLC. Data only."""
import json, os, glob, sys
sys.path.insert(0, '/Users/yuwang/.openclaw/workspace-claw-short/uw_short_fetch')
from uwsf.layers import level_stats, _levels
from uwsf.watchlist import WATCHLIST, tickers_of
WS = '/Users/yuwang/.openclaw/workspace-claw-short'
WL = tickers_of(WATCHLIST)
prices = json.load(open('/Users/yuwang/.openclaw/workspace-claw-short/analysis_data/backtest-2026-10-18/olivia_core/prices1y.json'))
px = {T: {d: v[:4] for d, v in prices[T].items()} for T in WL}
for D in ('2026-10-26', '2026-11-11'):
    for T in WL:
        for r in json.load(open(f'{WS}/analysis_data/{D}/{T}.json'))['price']['last_22_bars']:
            px[T][r[0]] = [r[1], r[2], r[3], r[4]]
lv = {T: {} for T in WL}
for T in WL:
    for f in glob.glob(f'/private/tmp/bt_trap/dp_raw/{T}/*.json'):
        b = json.load(open(f))['body']; lv[T][os.path.basename(f)[:-5]] = _levels(b.get('data') if isinstance(b, dict) else b)
    for f in glob.glob(f'{WS}/uw_short_fetch/cache/{T}/darkpool_levels_*.json'):
        d = os.path.basename(f).split('_')[2]
        b = json.load(open(f))['body']; x = _levels(b.get('data') if isinstance(b, dict) else b)
        if x: lv[T][d] = x
    pdd = json.load(open(f'{WS}/analysis_data/2026-11-11/{T}.json'))['darkpool_levels']['per_day']
    for d, x in pdd.items():
        if d not in lv[T]:
            rows = x['levels']; rows = rows['rows'] if isinstance(rows, dict) else rows
            lv[T][d] = {p: [dk, rg] for p, dk, rg in rows}
days = sorted(d for d in set(px['LITE']) if '2025-11-12' <= d <= '2026-11-11')
def agg(T, ds):
    a = {}
    for d in ds:
        for p, v in lv[T][d].items():
            q = a.setdefault(p, [0.0, 0.0]); q[0] += v[0]; q[1] += v[1]
    return a
out = {}
for T in WL:
    rows = []
    for i, d in enumerate(days):
        if d not in px[T] or d not in lv[T] or not lv[T][d]: continue
        o, h, l, c = px[T][d]
        r = {'date': d, 'open': o, 'high': h, 'low': l, 'close': c}
        for k, n in (('1D', 1), ('2D', 2), ('1W', 5), ('1M', 21)):
            ds = days[max(0, i - n + 1): i + 1]
            if len(ds) < n or any(x not in lv[T] or not lv[T][x] for x in ds):
                r['c' + k] = None; continue
            s = level_stats(agg(T, ds)); r['c' + k] = s['centroid_top8']
            if k == '1M':
                r['poc1M'] = s['poc']; r['avg1M'] = s['dark_total'] / n
        day = lv[T][d]
        r['dark'] = sum(v[0] for v in day.values())
        r['poc1D'] = max(day.items(), key=lambda kv: kv[1][0])[0]
        prices_ = sorted(p for p, v in day.items() if v[0] > 0)
        step = min((b - a for a, b in zip(prices_, prices_[1:]) if b > a), default=1.0)
        width = max(0.01 * c, step); best = None
        for j, a in enumerate(prices_):
            ins = [p for p in prices_[j:] if p < a + width]
            s_ = sum(day[p][0] for p in ins)
            if best is None or s_ > best[0]: best = (s_, ins[0], ins[-1])
        r['band_lo'], r['band_hi'], r['band_share'] = best[1], best[2], best[0] / r['dark'] if r['dark'] else None
        rows.append(r)
    out[T] = rows
json.dump({'days': days, 'panel': out}, open('/Users/yuwang/.openclaw/workspace-claw-short/analysis_data/backtest-2026-10-18/olivia_core/panel4.json', 'w'))
n1m = sum(1 for T in WL for r in out[T] if r.get('c1M'))
print('days', days[0], days[-1], len(days), '| name-days', sum(len(v) for v in out.values()), '| with 1M', n1m,
      '| first 1M day', min(r['date'] for T in WL for r in out[T] if r.get('c1M')))
missing = {T: [d for d in days if d not in lv[T]] for T in WL}
print('missing level days', {T: len(v) for T, v in missing.items() if v})
