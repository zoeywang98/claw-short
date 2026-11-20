# One-off (ZZ 2026-11-19 22:33 "复盘最近胜率"): v3 ✅ 做空 calls scored by price only, no stops / holding,
# split into the window since the last reviews (scans 11/10 onward) vs before, raw / vs 23-name average / vs β×average.
# β per name = OLS slope of daily returns on the 23-name equal-weight average, 7/17–10/16 (prices.json), as 11/10.
import json, os, re, statistics as st
WS = '/Users/yuwang/.openclaw/workspace-claw-short'
LOGS = f'{WS}/daily_short/logs'
SCANS = sorted(d for d in os.listdir(LOGS) if re.fullmatch(r'\d{4}-\d{2}-\d{2}', d) and d >= '2026-10-16')
WL = sorted(f[:-11] for f in os.listdir(f'{LOGS}/{SCANS[-1]}') if f.endswith('.reply.json') and not f.startswith('_'))
C = {}
for d in SCANS:
    for T in WL:
        p = f'{WS}/analysis_data/{d}/{T}.json'
        if os.path.exists(p):
            for bar in json.load(open(p))['price']['last_22_bars']:
                C[(T, bar[0])] = bar[4]
days = sorted({d for (_, d) in C}); idx = {d: i for i, d in enumerate(days)}; last = days[-1]
P = json.load(open(f'{WS}/analysis_data/backtest-2026-10-18/prices.json'))
pd = sorted(set.intersection(*[set(P[T]) for T in WL]))
pd = [d for d in pd if '2026-07-17' <= d <= '2026-10-16']
R = {T: [P[T][pd[i]][3] / P[T][pd[i - 1]][3] - 1 for i in range(1, len(pd))] for T in WL}
M = [st.mean(R[T][i] for T in WL) for i in range(len(pd) - 1)]
vm = st.pvariance(M); mm = st.mean(M)
BETA = {T: sum((r - st.mean(R[T])) * (m - mm) for r, m in zip(R[T], M)) / len(M) / vm for T in WL}
def end(d, k):
    j = idx[d] + k
    return days[j] if j < len(days) else None
rows = []
prev = {}
for d in SCANS:
    for T in WL:
        p = f'{LOGS}/{d}/{T}.reply.json'
        if not os.path.exists(p) or (T, d) not in C:
            continue
        t = json.load(open(p)).get('result') or ''
        m = re.search(r'\*\*结论\*\*[:：]\s*([^\n]*)', t); v = m.group(1) if m else ''
        b = json.load(open(f'{WS}/analysis_data/{d}/{T}.json'))
        c2 = b['darkpool_levels']['windows']['2D']['centroid_top8']
        e = {'d': d, 'T': T, 'short': v.startswith('✅ 做空'), 'hold': v.startswith('✅ 持有'), 'below': C[(T, d)] < c2}
        e['first'] = e['short'] and not prev.get(T, False); prev[T] = e['short']
        for k in (1, 3, 5):
            x = end(d, k)
            if x is None:
                e[k] = None; continue
            r = C[(T, x)] / C[(T, d)] - 1
            a = st.mean(C[(U, x)] / C[(U, d)] - 1 for U in WL)
            e[k] = (r, r - a, r - BETA[T] * a)
        rows.append(e)
def line(lab, E):
    out = []
    for k in (1, 3, 5):
        v = [e[k] for e in E if e[k] is not None]
        if not v:
            out.append(f'{k}D -'); continue
        out.append(f"{k}D 跌了{sum(r < 0 for r, _, _ in v) / len(v) * 100:3.0f}% 输平均{sum(x < 0 for _, x, _ in v) / len(v) * 100:3.0f}% "
                   f"输β{sum(y < 0 for _, _, y in v) / len(v) * 100:3.0f}% β超额{st.mean(y for _, _, y in v) * 100:+5.1f} n{len(v)}")
    print(f'{lab:26s} | ' + ' | '.join(out))
for lab, f in (('全部 10/16–', lambda d: True), ('之前 10/16–11/09', lambda d: d < '2026-11-10'), ('最近 11/10–', lambda d: d >= '2026-11-10')):
    E = [e for e in rows if f(e['d'])]
    print(f'== {lab}')
    line('✅ 做空', [e for e in E if e['short']])
    line('  其中新开', [e for e in E if e['first']])
    line('✅ 持有', [e for e in E if e['hold']])
    line('⚪ 跌破 2D 没中规则', [e for e in E if not e['short'] and not e['hold'] and e['below']])
    line('⚪ 在 2D 上方', [e for e in E if not e['short'] and not e['hold'] and not e['below']])
    line('全部 23 只', E)
print('\nβ:', ' '.join(f'{T}{BETA[T]:.2f}' for T in sorted(WL, key=lambda T: -BETA[T])))
print('board (23 avg) by day:', ' '.join(f"{days[i][5:]} {st.mean(C[(U, days[i])] / C[(U, days[i-1])] - 1 for U in WL)*100:+.1f}" for i in range(idx['2026-11-09'], len(days))))
