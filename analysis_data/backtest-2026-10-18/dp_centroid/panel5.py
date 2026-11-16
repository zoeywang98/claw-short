"""Per name-day DP centroid features, 2025-11-12 -> 2026-11-13, 23-name list (ZZ 2026-11-16 "只回测dp重心有关的规则").
Same sources and maths as olivia_core/panel4.py, extended to 11/13 and with the extra fields the DP-centroid rules need:
centroid_top8 for 1D/2D/3D/1W/1M, POC 1D/1M, 1M daily dark average, densest 1% band, where the 1D centroid sits in the
day's range (brief.day_flow logic, but without removing close-referenced block prints), share of 1W/1M dark volume
priced above the close. Data only, no judgement."""
import json, os, glob, sys
sys.path.insert(0, '/Users/yuwang/.openclaw/workspace-claw-short/uw_short_fetch')
from uwsf.layers import level_stats, _levels
from uwsf.watchlist import WATCHLIST, tickers_of
WS = '/Users/yuwang/.openclaw/workspace-claw-short'
OUT = f'{WS}/analysis_data/backtest-2026-10-18/dp_centroid/panel5.json'
WL = tickers_of(WATCHLIST)
LAST = '2026-11-13'
prices = json.load(open(f'{WS}/analysis_data/backtest-2026-10-18/olivia_core/prices1y.json'))
px = {T: {d: v[:4] for d, v in prices[T].items()} for T in WL}
# prices1y was pulled 11/12 13:07 -> its 11/12 bar is partial; the scan briefs' daily bars win
for D in ('2026-10-26', '2026-11-11', '2026-11-13'):
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
    pdd = json.load(open(f'{WS}/analysis_data/{LAST}/{T}.json'))['darkpool_levels']['per_day']
    for d, x in pdd.items():
        if d not in lv[T] or not lv[T][d]:
            rows = x['levels']; rows = rows['rows'] if isinstance(rows, dict) else rows
            lv[T][d] = {p: [dk, rg] for p, dk, rg in rows}
# NOW split 5-for-1: daily bars are split-adjusted, UW price-levels before 2025-12-18 are not -> rescale price and shares
for d, x in list(lv['NOW'].items()):
    if d < '2025-12-18':
        lv['NOW'][d] = {p / 5: [v[0] * 5, v[1] * 5] for p, v in x.items()}
days = sorted(d for d in set(px['LITE']) if '2025-11-12' <= d <= LAST)
def agg(T, ds):
    a = {}
    for d in ds:
        for p, v in lv[T][d].items():
            q = a.setdefault(p, [0.0, 0.0]); q[0] += v[0]; q[1] += v[1]
    return a
def bucket_of(price, labels):
    below = [p for p in labels if p <= price]
    return max(below) if below else None
out = {}
for T in WL:
    rows = []
    for i, d in enumerate(days):
        if d not in px[T] or d not in lv[T] or not lv[T][d]: continue
        o, h, l, c = px[T][d]
        r = {'date': d, 'open': o, 'high': h, 'low': l, 'close': c}
        for k, n in (('1D', 1), ('2D', 2), ('3D', 3), ('1W', 5), ('1M', 21)):
            ds = days[max(0, i - n + 1): i + 1]
            if len(ds) < n or any(x not in lv[T] or not lv[T][x] for x in ds):
                r['c' + k] = None; continue
            a = agg(T, ds); s = level_stats(a); r['c' + k] = s['centroid_top8']
            if k in ('1W', '1M'):
                tot = s['dark_total']
                r['above' + k] = sum(v[0] for p, v in a.items() if p > c) / tot if tot else None
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
        r['band_lo'], r['band_hi'] = best[1], best[2]
        # day_flow position of the 1D centroid between the buckets holding the day's low and high
        labels = [p for p in day]
        lo_b, hi_b = bucket_of(l, labels), bucket_of(h, labels)
        span = [p for p in prices_ if lo_b is not None and hi_b is not None and lo_b <= p <= hi_b]
        coarse = lo_b is None or hi_b is None or len(span) < 5 or hi_b == lo_b
        r['pos'] = None if coarse or r['c1D'] is None else (r['c1D'] - lo_b) / (hi_b - lo_b)
        rows.append(r)
    out[T] = rows
json.dump({'days': days, 'panel': out}, open(OUT, 'w'))
print('days', days[0], days[-1], len(days), '| name-days', sum(len(v) for v in out.values()),
      '| first 1M day', min(r['date'] for T in WL for r in out[T] if r.get('c1M')))
missing = {T: [d for d in days if d not in lv[T] or not lv[T][d]] for T in WL}
print('missing level days', {T: v for T, v in missing.items() if v})
# spot check vs the 11/13 scan briefs (2D / 1W / 1M centroid_top8)
bad = n = 0
for T in WL:
    b = json.load(open(f'{WS}/analysis_data/{LAST}/{T}.json'))['darkpool_levels']['windows']
    r = out[T][-1]
    for k in ('2D', '1W', '1M'):
        ref = b[k].get('centroid_top8'); n += 1
        if ref and r['c' + k] and abs(r['c' + k] / ref - 1) > 0.005: bad += 1; print('  diff', T, k, r['c' + k], ref)
print(f'brief check 11/13: {n - bad}/{n} within 0.5%')
