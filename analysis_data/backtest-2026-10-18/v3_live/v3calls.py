#!/usr/bin/env python3
"""Call-level v3 scorecard with no stops and no holding (ZZ 2026-10-30 "我不需要你算止损，再复盘一遍").
Every post-close ✅ 做空 (10/16 official rerun onward) is judged only by what the price did afterwards, close to close:
1/3/5 sessions later and to the latest close. 跌了 = price fell; 跑输 = did worse than the 23-name equal-weight average.
Control groups are split by price, not by verdict wording: no rule hit today, close below / above the 2D centroid.
Intraday rerun ✅ 做空 (logs/<date>_HHMM) are scored from the rerun price. Output: calls_<date>.txt."""
import json, os, re, statistics as st
WS = '/Users/yuwang/.openclaw/workspace-claw-short'
LOGS = f'{WS}/daily_short/logs'
SCANS = sorted(d for d in os.listdir(LOGS) if re.fullmatch(r'\d{4}-\d{2}-\d{2}', d) and d >= '2026-10-16')
WL = sorted(f[:-11] for f in os.listdir(f'{LOGS}/{SCANS[-1]}') if f.endswith('.reply.json') and not f.startswith('_'))
C = {}
for T in WL:
    for bar in json.load(open(f'{WS}/analysis_data/{SCANS[-1]}/{T}.json'))['price']['last_22_bars']:
        C[(T, bar[0])] = bar[4]
days = sorted({d for (_, d) in C}); idx = {d: i for i, d in enumerate(days)}; last = days[-1]
H = (1, 3, 5, 'now')
def end(d, k):
    j = idx[d] + k if k != 'now' else idx[last]
    return days[j] if idx[d] < j < len(days) else None
def ret(T, px, d, k):
    e = end(d, k)
    return C[(T, e)] / px - 1 if e else None
def avg(d, k):
    e = end(d, k)
    return st.mean(C[(T, e)] / C[(T, d)] - 1 for T in WL) if e else None
R = []
for d in SCANS:
    for T in WL:
        t = json.load(open(f'{LOGS}/{d}/{T}.reply.json')).get('result') or ''
        m = re.search(r'\*\*结论\*\*[:：]\s*([^\n]*)', t); v = m.group(1) if m else ''
        b = json.load(open(f'{WS}/analysis_data/{d}/{T}.json'))
        c2 = b['darkpool_levels']['windows']['2D']['centroid_top8']; close = C[(T, d)]
        rules = re.search(r'规则\s*([0-9、]+)', v) if v.startswith('✅ 做空') else None
        s = re.search(r'综合结构[:：]\s*([^，,*\n]+)', t)
        e = {'date': d, 'T': T, 'short': v.startswith('✅ 做空'), 'rules': rules.group(1).split('、') if rules else [],
             'qian': '· 浅' in v, 'below': close < c2, 'depth': (1 - close / c2) * 100, 'struct': s.group(1).strip() if s else '?'}
        for k in H:
            r = ret(T, close, d, k); a = avg(d, k)
            e[k] = None if r is None else (r, r - a)
        R.append(e)
# a new signal = ✅ 做空 when the name's previous scan was not ✅ 做空
prev = {}
for e in R:
    e['first'] = e['short'] and not prev.get(e['T'], False); prev[e['T']] = e['short']
def line(lab, E):
    out = []
    for k in H:
        v = [e[k] for e in E if e[k] is not None]
        if not v: out.append(f"{str(k):>3s}  -" + ' ' * 31); continue
        out.append(f"{str(k)+'D' if k != 'now' else '到' + last[5:]:>5s} 跌了 {sum(1 for r, x in v if r < 0)/len(v)*100:3.0f}% 跑输 {sum(1 for r, x in v if x < 0)/len(v)*100:3.0f}% 均 {st.mean(r for r, x in v)*100:+5.1f}% n{len(v):3d}")
    print(f'{lab:30s} | ' + ' | '.join(out))
short = [e for e in R if e['short']]
print(f'scans {SCANS[0]}..{SCANS[-1]} ({len(SCANS)}), closes to {last}; no stops, no holding\n')
line('✅ 做空 (every report)', short)
line('  new signals only', [e for e in short if e['first']])
line('no rule, close < 2D', [e for e in R if not e['short'] and e['below']])
line('no rule, close ≥ 2D', [e for e in R if not e['short'] and not e['below']])
line('all 23 names', R)
print()
for r in '1234':
    line(f'规则 {r}', [e for e in short if r in e['rules']])
line('规则 1/3 (crowded)', [e for e in short if set(e['rules']) & {'1', '3'}])
line('no 规则 1/3', [e for e in short if not set(e['rules']) & {'1', '3'}])
line('浅', [e for e in short if e['qian']]); line('not 浅', [e for e in short if not e['qian']])
# "strong" calls (ZZ 10/30 "那你喊强空的呢"; v3 has no such label): many rules at once, or 综合结构 偏空
line('3–4 条规则', [e for e in short if len(e['rules']) >= 3]); line('1–2 条规则', [e for e in short if len(e['rules']) <= 2])
line('4 条全中', [e for e in short if len(e['rules']) == 4])
line('综合结构 偏空', [e for e in short if e['struct'] == '偏空']); line('综合结构 中性', [e for e in short if e['struct'] == '中性'])
for lo, hi in ((0, 1), (1, 2), (2, 99)):
    line(f'{lo}–{hi}% below 2D', [e for e in short if lo <= e['depth'] < hi])
print()
for lab, f in (('scans 10/16–10/21', lambda d: d <= '2026-10-21'), ('scans 10/22–', lambda d: d >= '2026-10-22')):
    line(lab + ' ✅', [e for e in short if f(e['date'])]); line(lab + ' no rule', [e for e in R if not e['short'] and f(e['date'])])
print()
for d in SCANS:
    line(f'{d} ✅ ' + ' '.join(e['T'] for e in short if e['date'] == d)[:20], [e for e in short if e['date'] == d])
print('\n== new signals, each to the latest close (no stop)')
for e in sorted((e for e in short if e['first']), key=lambda e: (e['date'], e['T'])):
    n = e['now']
    print(f"  {e['date']} {e['T']:5s} 规则 {'、'.join(e['rules']):8s}{' 浅' if e['qian'] else '   '} 收盘 {C[(e['T'], e['date'])]:8.2f} → {last[5:]} "
          + ('   -' if n is None else f"{n[0]*100:+6.1f}% (同期平均 {(n[0]-n[1])*100:+5.1f}%)"))
print('\n== intraday rerun ✅ 做空, from the rerun price (0D = that day\'s close)')
IR = []
for d in sorted(x for x in os.listdir(LOGS) if re.fullmatch(r'\d{4}-\d{2}-\d{2}_\d{4}', x) and x >= '2026-10-19'):
    for f in sorted(x for x in os.listdir(f'{LOGS}/{d}') if x.endswith('.reply.json') and not x.startswith('_')):
        T = f[:-11]; t = json.load(open(f'{LOGS}/{d}/{f}')).get('result') or ''
        m = re.search(r'\*\*结论\*\*[:：]\s*([^\n]*)', t); v = m.group(1) if m else ''
        if not v.startswith('✅ 做空') or T not in WL or d[:10] not in idx: continue
        px = json.load(open(f'{WS}/analysis_data/{d}/{T}.json'))['price']['derived']['close']
        o = {0: C[(T, d[:10])] / px - 1, **{k: ret(T, px, d[:10], k) for k in H}}
        IR.append(o)
        print(f"  {d} {T:5s} {v[:22]:22s} 入 {px:8.2f} | " + ' | '.join(f"{k if k != 'now' else '到' + last[5:]}{'D' if k != 'now' else ''} {'  -  ' if o[k] is None else f'{o[k]*100:+5.1f}%'}" for k in (0, *H)))
for k in (0, *H):
    v = [o[k] for o in IR if o[k] is not None]
    if v: print(f"  {k}: 跌了 {sum(1 for x in v if x < 0)}/{len(v)}, 均 {st.mean(v)*100:+.1f}%")
