# One-off (ZZ 2026-11-27 13:37 "复盘最近胜率"): same method as recent_2026-11-19.py. v3 ✅ 做空 calls scored by price only,
# no stops / holding: raw / vs the 23-name average / vs β×average, 1/3/5 sessions and to the latest close.
# Windows: all scans 10/16–; before the last review (scans to 11/18); since it (scans 11/19–11/25).
# Closes: every scan brief's last_22_bars, plus the 11/27 half-day regular-session closes (UW ohlc/1d, market_time r,
# fetched 13:40 ET) from closes_2026-11-27.json. 11/26 market closed. Board = the 23 names scanned since 10/16 (AMD 11/24 and
# MU 11/25 are scored but not in the average). β = OLS slope on that average, 7/17–10/16 (prices.json; AMD/MU from closes file).
import json, os, re, statistics as st
WS = '/Users/yuwang/.openclaw/workspace-claw-short'
LOGS = f'{WS}/daily_short/logs'
HERE = os.path.dirname(os.path.abspath(__file__))
SCANS = sorted(d for d in os.listdir(LOGS) if re.fullmatch(r'\d{4}-\d{2}-\d{2}', d) and d >= '2026-10-16')
names_in = lambda d: {f[:-11] for f in os.listdir(f'{LOGS}/{d}') if f.endswith('.reply.json') and not f.startswith('_')}
NAMES = sorted(set().union(*(names_in(d) for d in SCANS)))
BOARD = sorted(names_in(SCANS[0]))
C = {}
for d in SCANS:
    for T in NAMES:
        p = f'{WS}/analysis_data/{d}/{T}.json'
        if os.path.exists(p):
            for bar in json.load(open(p))['price']['last_22_bars']:
                C[(T, bar[0])] = bar[4]
X = json.load(open(f'{HERE}/closes_2026-11-27.json'))
diff = [(T, d, C[(T, d)], c) for T in NAMES for d, c in X[T].items() if (T, d) in C and abs(C[(T, d)] / c - 1) > 1e-4]
for T in NAMES:
    for d, c in X[T].items():
        if d > SCANS[-1]:
            C[(T, d)] = c
days = sorted({d for (_, d) in C if d >= '2026-09-01'}); idx = {d: i for i, d in enumerate(days)}; last = days[-1]
P = json.load(open(f'{WS}/analysis_data/backtest-2026-10-18/prices.json'))
pd = [d for d in sorted(set.intersection(*[set(P[T]) for T in BOARD])) if '2026-07-17' <= d <= '2026-10-16']
px = lambda T, d: P[T][d][3] if T in P else X[T][d]
R = {T: [px(T, pd[i]) / px(T, pd[i - 1]) - 1 for i in range(1, len(pd))] for T in NAMES}
M = [st.mean(R[T][i] for T in BOARD) for i in range(len(pd) - 1)]
vm, mm = st.pvariance(M), st.mean(M)
BETA = {T: sum((r - st.mean(R[T])) * (m - mm) for r, m in zip(R[T], M)) / len(M) / vm for T in NAMES}
H = (1, 3, 5, 'now')
def end(d, k):
    j = idx[d] + k if k != 'now' else idx[last]
    return days[j] if idx[d] < j < len(days) else None
rows, prev = [], {}
for d in SCANS:
    for T in sorted(names_in(d)):
        if (T, d) not in C:
            continue
        t = json.load(open(f'{LOGS}/{d}/{T}.reply.json')).get('result') or ''
        m = re.search(r'\*\*结论\*\*[:：]\s*([^\n]*)', t); v = m.group(1) if m else ''
        c2 = json.load(open(f'{WS}/analysis_data/{d}/{T}.json'))['darkpool_levels']['windows']['2D']['centroid_top8']
        ru = re.search(r'规则\s*([0-9、]+)', v)
        e = {'d': d, 'T': T, 'v': v, 'short': v.startswith('✅ 做空'), 'hold': v.startswith('✅ 持有'), 'below': C[(T, d)] < c2,
             'rules': ru.group(1).split('、') if ru and v.startswith('✅ 做空') else [], 'qian': '· 浅' in v}
        e['first'] = e['short'] and not prev.get(T, False); prev[T] = e['short']
        for k in H:
            x = end(d, k)
            if x is None:
                e[k] = None; continue
            r = C[(T, x)] / C[(T, d)] - 1
            a = st.mean(C[(U, x)] / C[(U, d)] - 1 for U in BOARD)
            e[k] = (r, r - a, r - BETA[T] * a)
        rows.append(e)
def line(lab, E, hs=H):
    out = []
    for k in hs:
        v = [e[k] for e in E if e[k] is not None]
        kk = f'{k}D' if k != 'now' else '到' + last[5:]
        if not v:
            out.append(f'{kk} -'); continue
        out.append(f"{kk} 跌了{sum(r < 0 for r, _, _ in v) / len(v) * 100:3.0f}% 输平均{sum(x < 0 for _, x, _ in v) / len(v) * 100:3.0f}% "
                   f"输β{sum(y < 0 for _, _, y in v) / len(v) * 100:3.0f}% 均{st.mean(r for r, _, _ in v) * 100:+5.1f}% β超额{st.mean(y for _, _, y in v) * 100:+5.1f} n{len(v)}")
    print(f'{lab:22s} | ' + ' | '.join(out))
print(f'scans {SCANS[0]}..{SCANS[-1]} ({len(SCANS)}), closes to {last}; board = {len(BOARD)} names; brief vs fetched close mismatches: {len(diff)} {diff[:5]}\n')
for lab, f in (('全部 10/16–', lambda d: True), ('上次复盘前 10/16–11/18', lambda d: d <= '2026-11-18'), ('这次新增 11/19–11/25', lambda d: d >= '2026-11-19')):
    E = [e for e in rows if f(e['d'])]
    print(f'== {lab}')
    line('✅ 做空', [e for e in E if e['short']])
    line('  其中新开', [e for e in E if e['first']])
    line('  接着喊', [e for e in E if e['short'] and not e['first']])
    line('✅ 持有', [e for e in E if e['hold']])
    line('⚪ 跌破 2D 没中规则', [e for e in E if not e['short'] and not e['hold'] and e['below']])
    line('⚪ 在 2D 上方', [e for e in E if not e['short'] and not e['hold'] and not e['below']])
    line('全部', E)
    print()
print('== 这次新增 by scan (board = 23 avg)')
for d in [d for d in SCANS if d >= '2026-11-19']:
    S = [e for e in rows if e['d'] == d and e['short']]
    b = {k: (st.mean(C[(U, end(d, k))] / C[(U, d)] - 1 for U in BOARD) if end(d, k) else None) for k in H}
    print(f"{d} ✅做空 {len(S):2d} 持有 {sum(e['hold'] for e in rows if e['d'] == d):2d} ⚪ {sum(not e['short'] and not e['hold'] for e in rows if e['d'] == d):2d} | 板 "
          + ' '.join(f"{k}{'D' if k != 'now' else ''} {'-' if b[k] is None else f'{b[k]*100:+.1f}%'}" for k in H))
    line('   ✅ 做空', S)
    line('   ⚪+持有', [e for e in rows if e['d'] == d and not e['short']])
    for e in S:
        print(f"     {e['T']:5s} {'新' if e['first'] else '续'} 规则{'、'.join(e['rules']):8s}{'浅' if e['qian'] else '  '} β{BETA[e['T']]:4.2f} "
              + ' '.join(f"{k}{'D' if k != 'now' else ''} {'  -  ' if e[k] is None else f'{e[k][0]*100:+5.1f}%'}" for k in H))
print('\n== 规则（全部 / 这次新增），扣 β')
for lab, f in (('全部', lambda d: True), ('新增', lambda d: d >= '2026-11-19')):
    S = [e for e in rows if e['short'] and f(e['d'])]
    for r in '1234':
        line(f'{lab} 规则 {r}', [e for e in S if r in e['rules']], (1, 3, 5))
    line(f'{lab} 浅', [e for e in S if e['qian']], (1, 3, 5)); line(f'{lab} 不浅', [e for e in S if not e['qian']], (1, 3, 5))
print('\nβ:', ' '.join(f'{T}{BETA[T]:.2f}' for T in sorted(NAMES, key=lambda T: -BETA[T])))
print('board (23 avg) by day:', ' '.join(f"{days[i][5:]} {st.mean(C[(U, days[i])] / C[(U, days[i-1])] - 1 for U in BOARD)*100:+.1f}" for i in range(idx['2026-11-18'], len(days))))
print('board 11-18 → latest:', f"{st.mean(C[(U, last)] / C[(U, '2026-11-18')] - 1 for U in BOARD)*100:+.1f}%")
