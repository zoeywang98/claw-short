#!/usr/bin/env python3
"""Live v3 scorecard: every post-close v3 scan (10/16 official rerun, 10/19 onward), outcomes from closes up to the last available day.
Per report: 1/3/5-day close-to-close; 相对 = lagged the 23-name equal-weight average, 绝对 = price fell.
Per trade (SHORT_ENGINE 持有): enter at the ✅ 做空 close when nothing is held, stop = that day's 2D centroid, exit on a close above it or after 10 sessions; open trades marked to the last close."""
import json, os, re, statistics as st, collections
WS = '/Users/yuwang/.openclaw/workspace-claw-short'
LOGS = f'{WS}/daily_short/logs'
SCANS = sorted(d for d in os.listdir(LOGS) if re.fullmatch(r'\d{4}-\d{2}-\d{2}', d) and d >= '2026-10-16')   # post-close scans only (10/16 = official v3 rerun)
WL = sorted(f[:-11] for f in os.listdir(f'{LOGS}/{SCANS[-1]}') if f.endswith('.reply.json') and not f.startswith('_'))
C = {}
for T in WL:   # closes from the latest scan's briefs (22 sessions)
    for bar in json.load(open(f'{WS}/analysis_data/{SCANS[-1]}/{T}.json'))['price']['last_22_bars']:
        C[(T, bar[0])] = bar[4]
days = sorted({d for (_, d) in C})
idx = {d: i for i, d in enumerate(days)}
def fwd(T, d, k):
    i = idx[d]
    if i + k >= len(days): return None
    a, b = C.get((T, d)), C.get((T, days[i + k]))
    return b / a - 1 if a and b else None
avg = {(d, k): (lambda v: sum(v) / len(v) if len(v) >= 15 else None)([x for x in (fwd(T, d, k) for T in WL) if x is not None]) for d in SCANS for k in (1, 3, 5)}
R = []
for d in SCANS:
    for T in WL:
        t = json.load(open(f'{WS}/daily_short/logs/{d}/{T}.reply.json')).get('result') or ''
        m = re.search(r'\*\*结论\*\*[:：]\s*([^\n]*)', t); v = m.group(1) if m else ''
        b = json.load(open(f'{WS}/analysis_data/{d}/{T}.json'))
        c2 = b['darkpool_levels']['windows']['2D']['centroid_top8']; close = b['price']['derived']['close']
        if abs(close - C[(T, d)]) / close > 0.002: print('close mismatch', d, T, close, C[(T, d)])
        kind = 'new' if v.startswith('✅ 做空') else 'hold' if v.startswith('✅ 持有') else 'none'
        rules = re.search(r'规则\s*([0-9、]+)', v) if kind == 'new' else None
        e = {'date': d, 'T': T, 'kind': kind, 'rules': rules.group(1).split('、') if rules else [], 'qian': '· 浅' in v,
             'cont': '持有自' in v, 'stop2D': c2, 'close': close, 'v': v}
        for k in (1, 3, 5):
            f = fwd(T, d, k); e[f'r{k}'] = f
            e[f'e{k}'] = f - avg[(d, k)] if f is not None and avg[(d, k)] is not None else None
        R.append(e)
def wr(E, k):
    v = [e for e in E if e.get(f'e{k}') is not None]
    if not v: return '   -   '
    return (f"相对 {sum(1 for e in v if e[f'e{k}'] < 0)/len(v)*100:3.0f}% 绝对 {sum(1 for e in v if e[f'r{k}'] < 0)/len(v)*100:3.0f}% "
            f"均值 {st.mean(e[f'r{k}'] for e in v)*100:+5.1f}% 超额 {st.mean(e[f'e{k}'] for e in v)*100:+5.1f}% n{len(v):3d}")
def show(lab, E):
    print(f'{lab:34s} | 1D {wr(E,1)} | 3D {wr(E,3)} | 5D {wr(E,5)}')
print('23-name average:', {d: tuple(None if avg[(d, k)] is None else round(avg[(d, k)] * 100, 1) for k in (1, 3, 5)) for d in SCANS})
print('\n== per report (each scan day counts once per name)')
new = [e for e in R if e['kind'] == 'new']
show('✅ 做空 (rules hit today)', new)
show('  first entry (not 持有自)', [e for e in new if not e['cont']])
show('  浅', [e for e in new if e['qian']]); show('  not 浅', [e for e in new if not e['qian']])
for r in '1234': show(f'  规则 {r}', [e for e in new if r in e['rules']])
show('✅ 持有 (held, no rule today)', [e for e in R if e['kind'] == 'hold'])
show('✅ any (做空 + 持有)', [e for e in R if e['kind'] != 'none'])
show('⚪ 不做空', [e for e in R if e['kind'] == 'none'])
show('  ⚪ 没跌破 2D', [e for e in R if e['kind'] == 'none' and '没跌破 2D' in e['v']])
show('  ⚪ 跌破 2D 但没命中规则', [e for e in R if e['kind'] == 'none' and '没命中规则' in e['v']])
for d in SCANS:
    show(f'  {d} ✅做空 vs ⚪', [e for e in new if e['date'] == d]); show(f'  {d} ⚪', [e for e in R if e['date'] == d and e['kind'] == 'none'])
# trades
print('\n== trades (持有 rule)')
last = days[-1]
trades = []
for T in WL:
    act = None
    for d in SCANS:
        e = next(x for x in R if x['date'] == d and x['T'] == T)
        if act:
            held = idx[d] - idx[act['entry']]
            if C[(T, d)] > act['stop'] or held >= 10:
                act.update(exit=d, exit_close=C[(T, d)], why='stop' if C[(T, d)] > act['stop'] else '10d'); trades.append(act); act = None
        if not act and e['kind'] == 'new':
            act = {'T': T, 'entry': d, 'entry_close': e['close'], 'stop': e['stop2D'], 'rules': '、'.join(e['rules']), 'qian': e['qian']}
    if act:
        act.update(exit=None, exit_close=C[(T, last)], why='open'); trades.append(act)
for t in trades:
    t['pnl'] = -(t['exit_close'] / t['entry_close'] - 1)
    i0 = idx[t['entry']]; i1 = idx[t['exit'] or last]
    t['avg'] = (sum(C[(X, days[i1])] / C[(X, days[i0])] - 1 for X in WL) / len(WL))
    t['rel'] = t['pnl'] + t['avg']       # short P&L minus what shorting the 23-name basket would have made
for t in sorted(trades, key=lambda t: (t['entry'], t['T'])):
    print(f"  {t['T']:5s} {t['entry']} 规则 {t['rules']:8s}{' 浅' if t['qian'] else '   '} 入 {t['entry_close']:8.2f} 失效 {t['stop']:8.2f} → {t['exit'] or '持有中':10s} {t['exit_close']:8.2f} ({t['why']:4s}) 空单 {t['pnl']*100:+6.1f}% 同期平均 {t['avg']*100:+5.1f}%")
cl = [t for t in trades if t['why'] != 'open']; op = [t for t in trades if t['why'] == 'open']
for lab, E in (('closed', cl), ('open (marked to ' + last + ')', op), ('all', trades), ('all 浅', [t for t in trades if t['qian']]), ('all not 浅', [t for t in trades if not t['qian']])):
    if E: print(f"{lab:28s} n {len(E):2d} 赚钱 {sum(1 for t in E if t['pnl'] > 0)/len(E)*100:3.0f}% 平均 {st.mean(t['pnl'] for t in E)*100:+5.1f}% 中位 {st.median(t['pnl'] for t in E)*100:+5.1f}% | 跑赢做空平均 {sum(1 for t in E if t['rel'] > 0)/len(E)*100:3.0f}%")
json.dump({'reports': R, 'trades': trades}, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'v3live.json'), 'w'), ensure_ascii=False, default=str)
