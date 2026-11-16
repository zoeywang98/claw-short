"""Does the DP centroid add anything over plain price extension? Same thresholds against the plain average close of the
same window (2D / 5D / 21D), and the extended names split by whether the DP centroid lags the average close."""
from dp_rules import events, score, BASEK, dedup, QS, close, verdict
def sma(T, i, n):
    v = [close(T, j) for j in range(i - n + 1, i + 1)]
    return sum(v) / n if all(v) else None
def line(name, E):
    s = score(E, 5, 'bear'); s10 = score(E, 10, 'bear'); b = score(E, 5, 'bear', 'b'); d = score(dedup(E), 5, 'bear')
    qs = [score([e for e in E if lo <= e['date'] <= hi], 5, 'bear') for lo, hi, _ in QS]
    print(f"{name:44s} 5D 跑输{s['hit']*100:3.0f}% 跌{s['fell']*100:3.0f}% 超额{s['mx']*100:+5.1f} td{s['td']:+.1f} n{s['n']:4d} | 10D 跑输{s10['hit']*100:3.0f}% 跌{s10['fell']*100:3.0f}% 超额{s10['mx']*100:+5.1f} | β5D {b['mx']*100:+.1f} td{b['td']:+.1f} | 首次 {d['hit']*100:.0f}%/跌{d['fell']*100:.0f}% n{d['n']} | 季度 "
          + '/'.join(f"{q['hit']*100:.0f}" if q else '-' for q in qs) + f" | 判定 {verdict(E, 'bear')}")
print('基准 5D 跑输 55% 跌 47%；10D 跑输 56% 跌 48%')
for lab, w, n, xs in (('2D', 'c2D', 2, (0.05,)), ('1W', 'c1W', 5, (0.08, 0.15)), ('1M', 'c1M', 21, (0.10, 0.20, 0.30))):
    for x in xs:
        line(f'DP：收盘高出 {lab} 重心 ≥{x*100:.0f}%', events(lambda T, i, r, w=w, x=x: r['close'] >= (1 + x) * r[w]))
        line(f'价：收盘高出 {n} 日均价 ≥{x*100:.0f}%', events(lambda T, i, r, n=n, x=x: sma(T, i, n) and r['close'] >= (1 + x) * sma(T, i, n)))
print('--- 都高出 21 日均价 ≥20% 的票里，按 1M 暗池重心在均价下方（库存没跟上）还是上方拆')
ext = lambda T, i, r: sma(T, i, 21) and r['close'] >= 1.2 * sma(T, i, 21)
line('  1M 重心比 21 日均价低 ≥3%（库存没跟上）', events(lambda T, i, r: ext(T, i, r) and r['c1M'] <= 0.97 * sma(T, i, 21)))
line('  1M 重心在 21 日均价 ±3% 内', events(lambda T, i, r: ext(T, i, r) and 0.97 * sma(T, i, 21) < r['c1M'] < 1.03 * sma(T, i, 21)))
line('  1M 重心比 21 日均价高 ≥3%', events(lambda T, i, r: ext(T, i, r) and r['c1M'] >= 1.03 * sma(T, i, 21)))
ext5 = lambda T, i, r: sma(T, i, 5) and r['close'] >= 1.08 * sma(T, i, 5)
line('  高出 5 日均价 ≥8%，1W 重心比 5 日均价低 ≥2%', events(lambda T, i, r: ext5(T, i, r) and r['c1W'] <= 0.98 * sma(T, i, 5)))
line('  高出 5 日均价 ≥8%，1W 重心不低于 5 日均价 −2%', events(lambda T, i, r: ext5(T, i, r) and r['c1W'] > 0.98 * sma(T, i, 5)))
