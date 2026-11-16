"""Sensitivity for the one rule whose hit rate beat the base in every quarter: Step 4 "price runs ahead of the DP inventory"
(close X% above the 2D / 1W / 1M centroid). Same outcome definitions as dp_rules.py."""
import statistics as st
from dp_rules import events, score, BASEK, dedup, QS, OPT, H
def line(name, E):
    out = [f'{name:34s}']
    for k in H:
        s = score(E, k, 'bear'); b = BASEK[(k, 'bear', 'x')]
        if not s: out.append(f'{k}D n0'); continue
        out.append(f"{k}D 跑输{s['hit']*100:3.0f}%({b['hit']*100:.0f}) 跌{s['fell']*100:3.0f}%({b['fell']*100:.0f}) 超额{s['mx']*100:+5.1f}/中位{s['med']*100:+5.1f} n{s['n']}")
    d = score(dedup(E), 5, 'bear'); bb = score(E, 5, 'bear', 'b')
    qs = [score([e for e in E if lo <= e['date'] <= hi], 5, 'bear') for lo, hi, _ in QS]
    out.append(f"| 首次5D {d['hit']*100:.0f}%/跌{d['fell']*100:.0f}% n{d['n']} | β5D {bb['hit']*100:.0f}%/{bb['mx']*100:+.1f} | 季度 " + '/'.join(f"{q['hit']*100:.0f}" if q else '-' for q in qs))
    v5 = sorted(e['x5'] for e in E if e['x5'] is not None)
    if v5:
        k = max(1, len(v5) // 20)
        out.append(f"| 去掉最好最差各5% 平均{st.mean(v5[k:-k])*100:+.1f} | 5天跌≥5% {sum(1 for e in E if e['r5'] is not None and e['r5'] <= -0.05)/len(v5)*100:.0f}%")
    print(' '.join(out))
base = events(lambda T, i, r: True)
print('5天跌≥5% 基准', f"{sum(1 for e in base if e['r5'] is not None and e['r5'] <= -0.05)/sum(1 for e in base if e['r5'] is not None)*100:.0f}%")
for w, xs in (('c2D', (0.03, 0.05, 0.08)), ('c1W', (0.05, 0.08, 0.12, 0.15)), ('c1M', (0.10, 0.15, 0.20, 0.30))):
    for x in xs:
        E = events(lambda T, i, r, w=w, x=x: r['close'] >= (1 + x) * r[w])
        line(f'收盘高出 {w[1:]} 重心 ≥{x*100:.0f}%', E)
E = events(lambda T, i, r: r['close'] >= 1.08 * r['c1W'])
line('  ≥8% 1W · 光模块', [e for e in E if e['T'] in OPT]); line('  ≥8% 1W · 其他', [e for e in E if e['T'] not in OPT])
for lo, hi, lab in QS: line(f'  ≥8% 1W · {lab}', [e for e in E if lo <= e['date'] <= hi])
import collections
print('≥8% 1W 按票（name-days）', collections.Counter(e['T'] for e in E).most_common())
