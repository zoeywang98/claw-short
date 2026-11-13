import json, math, statistics as st, sys
P = json.load(open('/Users/yuwang/.openclaw/workspace-claw-short/analysis_data/backtest-2026-10-18/olivia_core/panel2.json')); days = P['days']; panel = P['panel']
WS = '/Users/yuwang/.openclaw/workspace-claw-short'
# cross-check vs scan briefs
import os
diffs = []
for D in ('2026-10-16', '2026-11-04', '2026-11-11'):
    for T in panel:
        f = f'{WS}/analysis_data/{D}/{T}.json'
        if not os.path.exists(f): continue
        w = json.load(open(f))['darkpool_levels']['windows']
        r = next((x for x in panel[T] if x['date'] == D), None)
        for k in ('2D', '1M'):
            if r and r.get('c' + k) and w.get(k, {}).get('centroid_top8'):
                diffs.append(abs(r['c' + k] / w[k]['centroid_top8'] - 1))
print('crosscheck n', len(diffs), 'max diff %.4f' % max(diffs), '>0.5%:', sum(d > 0.005 for d in diffs))
idx = {d: i for i, d in enumerate(days)}
rows = []
for T, rs in panel.items():
    byd = {r['date']: r for r in rs}
    for r in rs:
        i = idx[r['date']]
        prev = byd.get(days[i - 1]) if i > 0 else None
        r = dict(r, T=T)
        r['pc'] = prev['close'] if prev else None
        for k in (1, 3, 5):
            nx = byd.get(days[i + k]) if i + k < len(days) else None
            r[f'r{k}'] = nx['close'] / r['close'] - 1 if nx else None
        r['prev'] = prev
        rows.append(r)
bench = {}
for k in (1, 3, 5):
    for d in days:
        v = [r[f'r{k}'] for r in rows if r['date'] == d and r[f'r{k}'] is not None]
        bench[(k, d)] = sum(v) / len(v) if len(v) >= 20 else None
for r in rows:
    for k in (1, 3, 5):
        b = bench.get((k, r['date']))
        r[f'x{k}'] = r[f'r{k}'] - b if (b is not None and r[f'r{k}'] is not None) else None
def ok(r): return r.get('c1M') is not None and r['date'] >= '2026-08-13'
def vs(r): return r['dark'] / r['avg1M'] if r.get('avg1M') else 0
def up(r): return r['pc'] and (r['high'] / r['pc'] - 1) >= (1 - r['low'] / r['pc'])
def summ(name, sel):
    out = [name]
    for k in (1, 3, 5):
        ev = [r for r in sel if r[f'x{k}'] is not None]
        if not ev: out.append(f'{k}D n0'); continue
        fell = sum(r[f'r{k}'] < 0 for r in ev) / len(ev)
        under = sum(r[f'x{k}'] < 0 for r in ev) / len(ev)
        mx = sum(r[f'x{k}'] for r in ev) / len(ev)
        byd = {}
        for r in ev: byd.setdefault(r['date'], []).append(r[f'x{k}'])
        dm = [sum(v) / len(v) for v in byd.values()]
        t = (st.mean(dm) / (st.stdev(dm) / math.sqrt(len(dm)))) if len(dm) > 2 and st.stdev(dm) > 0 else float('nan')
        out.append(f'{k}D n{len(ev)} 跌{fell:.0%} 跑输{under:.0%} 超额{100*mx:+.1f}pp td{t:+.1f}')
    print(' | '.join(out))
base = [r for r in rows if ok(r)]
S = {
 'BASE 全部': base,
 'V3 前提 close<2D': [r for r in base if r['c2D'] and r['close'] < r['c2D']],
 'O1 放量1.3x & close<当天最密带 & <1M重心': [r for r in base if vs(r) >= 1.3 and r['close'] < r['band_lo'] and r['close'] < r['c1M']],
 'O2 放量1.0x & close<当天POC & <1M重心': [r for r in base if vs(r) >= 1.0 and r['close'] < r['poc1D'] and r['close'] < r['c1M']],
 'O4 放量1.3x & close<1D重心 & <1M重心': [r for r in base if vs(r) >= 1.3 and r['close'] < r['c1D'] and r['close'] < r['c1M']],
 'O3 不看量 close<1D重心 & <1M重心': [r for r in base if r['close'] < r['c1D'] and r['close'] < r['c1M']],
 'O1 但 close>=1M重心（对照）': [r for r in base if vs(r) >= 1.3 and r['close'] < r['band_lo'] and r['close'] >= r['c1M']],
 'O1 当天先冲高(up day)': [r for r in base if vs(r) >= 1.3 and r['close'] < r['band_lo'] and r['close'] < r['c1M'] and up(r)],
 'O1 当天下跌(down day)': [r for r in base if vs(r) >= 1.3 and r['close'] < r['band_lo'] and r['close'] < r['c1M'] and not up(r)],
 'O1 当天跌>3%': [r for r in base if vs(r) >= 1.3 and r['close'] < r['band_lo'] and r['close'] < r['c1M'] and r['pc'] and r['close'] / r['pc'] - 1 <= -0.03],
 'O1 当天跌<=3%或涨': [r for r in base if vs(r) >= 1.3 and r['close'] < r['band_lo'] and r['close'] < r['c1M'] and r['pc'] and r['close'] / r['pc'] - 1 > -0.03],
 'O3 第一天进入': [r for r in base if r['close'] < r['c1D'] and r['close'] < r['c1M'] and r['prev'] and r['prev'].get('c1M') and r['prev'].get('c1D') and not (r['prev']['close'] < r['prev']['c1D'] and r['prev']['close'] < r['prev']['c1M'])],
}
for name, sel in S.items():
    summ(name, sel)
print('--- halves (O1 / O3 / V3P)')
for lo_, hi_ in (('2026-08-13', '2026-09-24'), ('2026-09-25', '2026-11-11')):
    for name in ('BASE 全部', 'O1 放量1.3x & close<当天最密带 & <1M重心', 'O3 不看量 close<1D重心 & <1M重心', 'V3 前提 close<2D'):
        summ(f'{lo_[5:]}–{hi_[5:]} {name}', [r for r in S[name] if lo_ <= r['date'] <= hi_])
json.dump([{k: r[k] for k in ('T', 'date', 'close', 'pc', 'c1D', 'c2D', 'c1M', 'band_lo', 'poc1D', 'dark', 'avg1M', 'r1', 'r3', 'r5', 'x1', 'x3', 'x5')} for r in S['O1 放量1.3x & close<当天最密带 & <1M重心']], open('/Users/yuwang/.openclaw/workspace-claw-short/analysis_data/backtest-2026-10-18/olivia_core/o1_events.json', 'w'))
