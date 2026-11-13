"""ZZ 11/12: 放量冲上去，收盘掉回大量价位下面，但还在长周期核心上方 -> forward 1/3/5/10D vs the 23-name average."""
import json, math, os, re, statistics as st
P = json.load(open('/Users/yuwang/.openclaw/workspace-claw-short/analysis_data/backtest-2026-10-18/olivia_core/panel4.json')); days = P['days']; panel = P['panel']
WS = '/Users/yuwang/.openclaw/workspace-claw-short'
OPT = {'LITE', 'COHR', 'AAOI', 'GLW', 'AEHR'}
H = (1, 3, 5, 10)
idx = {d: i for i, d in enumerate(days)}
rows = []
for T, rs in panel.items():
    byd = {r['date']: r for r in rs}
    for r in rs:
        i = idx[r['date']]; prev = byd.get(days[i - 1]) if i > 0 else None
        r = dict(r, T=T, pc=prev['close'] if prev else None)
        for k in H:
            nx = byd.get(days[i + k]) if i + k < len(days) else None
            r[f'r{k}'] = nx['close'] / r['close'] - 1 if nx else None
        rows.append(r)
bench = {}
for k in H:
    acc = {}
    for r in rows:
        if r[f'r{k}'] is not None: acc.setdefault(r['date'], []).append(r[f'r{k}'])
    bench[k] = {d: sum(v) / len(v) for d, v in acc.items() if len(v) >= 20}
for r in rows:
    for k in H:
        b = bench[k].get(r['date']); r[f'x{k}'] = r[f'r{k}'] - b if (b is not None and r[f'r{k}'] is not None) else None
base = [r for r in rows if r.get('c1M') and r['pc'] and r['date'] >= '2025-12-11']
vs = lambda r: r['dark'] / r['avg1M'] if r.get('avg1M') else 0
hi = lambda r: r['high'] / r['pc'] - 1
moveup = lambda r: (r['high'] / r['pc'] - 1) >= (1 - r['low'] / r['pc'])
def summ(name, sel, hs=H):
    out = [f'{name} [{len(set(r["date"] for r in sel))}天]']
    for k in hs:
        ev = [r for r in sel if r[f'x{k}'] is not None]
        if not ev: out.append(f'{k}D n0'); continue
        under = sum(r[f'x{k}'] < 0 for r in ev) / len(ev); fell = sum(r[f'r{k}'] < 0 for r in ev) / len(ev)
        mx = sum(r[f'x{k}'] for r in ev) / len(ev); med = st.median(r[f'x{k}'] for r in ev)
        byd = {}
        for r in ev: byd.setdefault(r['date'], []).append(r[f'x{k}'])
        dm = [sum(v) / len(v) for v in byd.values()]
        t = st.mean(dm) / (st.stdev(dm) / math.sqrt(len(dm))) if len(dm) > 2 and st.stdev(dm) > 0 else float('nan')
        out.append(f'{k}D n{len(ev)} 跑输{under:.0%} 跌{fell:.0%} 超额{100*mx:+.1f}/中位{100*med:+.1f}pp td{t:+.1f}')
    print(' | '.join(out))
def pat(r, v=1.3, push='up', below='band', core='c1M'):
    if vs(r) < v: return False
    if push == 'up' and not moveup(r): return False
    if isinstance(push, float) and hi(r) < push: return False
    ref = {'band': r['band_lo'], 'poc': r['poc1D'], 'c1D': r['c1D'], 'c2D': r['c2D']}[below]
    if ref is None or not r['close'] < ref: return False
    return r[core] is not None and r['close'] >= r[core]

def olivia(r, v=1.3, below='band', core='c1M'):
    if vs(r) < v: return False
    ref = {'band': r['band_lo'], 'poc': r['poc1D'], 'c1D': r['c1D'], 'c2D': r['c2D']}[below]
    return ref is not None and r['close'] < ref and r[core] is not None and r['close'] < r[core]
O = [r for r in base if olivia(r)]
print('样本', min(r['date'] for r in base), '→', max(r['date'] for r in base), '23 只, name-days', len(base))
summ('全部（基准）', base)
summ('★ 原口径：放量1.3x + 收盘<当天最密带 + <1M重心', O)
print('--- 口径敏感度')
for v in (1.0, 1.5, 2.0): summ(f'放量{v}x', [r for r in base if olivia(r, v=v)])
for b in ('poc', 'c1D', 'c2D'): summ(f'"大量价位"={b}', [r for r in base if olivia(r, below=b)])
summ('长周期核心=1M POC', [r for r in base if olivia(r, core='poc1M')])
summ('不看量：收盘<1D重心 + <1M重心', [r for r in base if r['close'] < r['c1D'] and r['close'] < r['c1M']])
summ('不看量：收盘<2D重心 + <1M重心', [r for r in base if r['c2D'] and r['close'] < r['c2D'] and r['close'] < r['c1M']])
summ('v3 前提：收盘<2D重心', [r for r in base if r['c2D'] and r['close'] < r['c2D']])
print('--- 拆分（原口径）')
summ('当天冲高（move=up）', [r for r in O if moveup(r)]); summ('当天下砸（move=down）', [r for r in O if not moveup(r)])
summ('当天跌>3%', [r for r in O if r['close'] / r['pc'] - 1 <= -0.03]); summ('当天跌≤3%或涨', [r for r in O if r['close'] / r['pc'] - 1 > -0.03])
summ('光模块', [r for r in O if r['T'] in OPT]); summ('其他', [r for r in O if r['T'] not in OPT])
for lo_, hi_ in (('2025-12-11', '2026-02-28'), ('2026-03-01', '2026-05-31'), ('2026-06-01', '2026-08-31'), ('2026-09-01', '2026-11-11')):
    summ(f'{lo_}~{hi_[5:]}', [r for r in O if lo_ <= r['date'] <= hi_])
last = {}; dedup = []
for r in sorted(O, key=lambda r: (r['T'], r['date'])):
    if r['T'] in last and idx[r['date']] - idx[last[r['T']]] <= 5: continue
    last[r['T']] = r['date']; dedup.append(r)
summ('同一只 5 天内只算第一次', dedup)
print('--- 对照（同一年）')
summ('放量1.3x + 收盘<当天最密带 + ≥1M重心', [r for r in base if vs(r) >= 1.3 and r['close'] < r['band_lo'] and r['close'] >= r['c1M']])
summ('ZZ 第二问：放量1.3x + 冲高 + 收盘<最密带 + ≥1M', [r for r in base if pat(r)])
from collections import Counter
print('每月次数', sorted(Counter(r['date'][:7] for r in O).items()))
print('按票', Counter(r['T'] for r in O).most_common())
json.dump([{k: r[k] for k in ('T', 'date', 'close', 'pc', 'high', 'low', 'band_lo', 'c1D', 'c2D', 'c1M', 'dark', 'avg1M', 'x1', 'x3', 'x5', 'x10')} for r in O], open('/Users/yuwang/.openclaw/workspace-claw-short/analysis_data/backtest-2026-10-18/olivia_core/olivia_year_events.json', 'w'))
