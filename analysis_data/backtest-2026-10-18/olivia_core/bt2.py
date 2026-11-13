"""ZZ 11/12: 放量冲上去，收盘掉回大量价位下面，但还在长周期核心上方 -> forward 1/3/5/10D vs the 23-name average."""
import json, math, os, re, statistics as st
P = json.load(open('/Users/yuwang/.openclaw/workspace-claw-short/analysis_data/backtest-2026-10-18/olivia_core/panel3.json')); days = P['days']; panel = P['panel']
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
base = [r for r in rows if r.get('c1M') and r['pc'] and r['date'] >= '2026-04-30']
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
MAIN = [r for r in base if pat(r)]
print('样本', base[0]['date'] if base else None, '→', max(r['date'] for r in base), '名单 23 只, name-days', len(base))
summ('全部（基准）', base)
summ('★ 主口径：放量1.3x + 冲高(上影大于下影) + 收盘<当天最密带 + ≥1M重心', MAIN)
summ('  对照A：同上但收盘<1M重心', [r for r in base if vs(r) >= 1.3 and moveup(r) and r['close'] < r['band_lo'] and r['close'] < r['c1M']])
summ('  对照B：放量1.3x + 冲高 + 收盘守在最密带上（≥带上沿）+ ≥1M', [r for r in base if vs(r) >= 1.3 and moveup(r) and r['close'] >= r['band_hi'] and r['close'] >= r['c1M']])
summ('  对照C：不放量(<1.0x) + 冲高 + 收盘<最密带 + ≥1M', [r for r in base if vs(r) < 1.0 and moveup(r) and r['close'] < r['band_lo'] and r['close'] >= r['c1M']])
print('--- 口径敏感度')
for v in (1.0, 1.5, 2.0): summ(f'放量{v}x', [r for r in base if pat(r, v=v)])
for p in (0.03, 0.05): summ(f'冲高=最高比昨收≥{int(p*100)}%', [r for r in base if pat(r, push=p)])
for b in ('poc', 'c1D', 'c2D'): summ(f'"大量价位"={b}', [r for r in base if pat(r, below=b)])
summ('长周期核心=1M POC', [r for r in base if pat(r, core='poc1M')])
print('--- 拆分（主口径）')
summ('光模块', [r for r in MAIN if r['T'] in OPT]); summ('其他', [r for r in MAIN if r['T'] not in OPT])
for lo_, hi_ in (('2026-04-30', '2026-07-31'), ('2026-08-01', '2026-11-11')): summ(f'{lo_[5:]}–{hi_[5:]}', [r for r in MAIN if lo_ <= r['date'] <= hi_])
last = {}; dedup = []
for r in sorted(MAIN, key=lambda r: (r['T'], r['date'])):
    if r['T'] in last and idx[r['date']] - idx[last[r['T']]] <= 5: continue
    last[r['T']] = r['date']; dedup.append(r)
summ('同一只 5 天内只算第一次', dedup)
summ('当天收涨（close>昨收）', [r for r in MAIN if r['close'] > r['pc']]); summ('当天收跌', [r for r in MAIN if r['close'] <= r['pc']])
print('--- 事件明细（主口径）')
def verdict(d, T):
    f = f'{WS}/daily_short/logs/{d}/{T}.reply.json'
    if not os.path.exists(f): return ''
    m = re.search(r'\*\*结论\*\*[:：]\s*([^·\n]*·?[^·\n]*)', json.load(open(f)).get('result') or '')
    return m.group(1).strip()[:22] if m else '?'
for r in sorted(MAIN, key=lambda r: r['date']):
    f = lambda k: '  -  ' if r[f'x{k}'] is None else f"{100*r[f'x{k}']:+5.1f}"
    print(f"  {r['date']} {r['T']:5s} 高{100*hi(r):+5.1f}% 收{100*(r['close']/r['pc']-1):+5.1f}% 量{vs(r):.2f}x 收/1M{100*(r['close']/r['c1M']-1):+5.1f}% 超额3D{f(3)} 5D{f(5)} 10D{f(10)} {verdict(r['date'], r['T'])}")
json.dump([{k: r[k] for k in ('T', 'date', 'close', 'pc', 'high', 'band_lo', 'c1D', 'c2D', 'c1M', 'dark', 'avg1M', 'x1', 'x3', 'x5', 'x10')} for r in MAIN], open('/Users/yuwang/.openclaw/workspace-claw-short/analysis_data/backtest-2026-10-18/olivia_core/main_events.json', 'w'))
