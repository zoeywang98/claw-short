import json
recs = json.load(open('/tmp/bt/joined.json'))
def m(sel, k):
    v = [r[f'e{k}'] for r in sel if r.get(f'e{k}') is not None]
    raw = [r[f'r{k}'] for r in sel if r.get(f'r{k}') is not None]
    if not v: return '-'
    return f"n={len(v)} exc {sum(v)/len(v)*100:+.2f}% (below avg {sum(1 for x in v if x<0)/len(v)*100:.0f}%) raw {sum(raw)/len(raw)*100:+.2f}%"
tests = [
  ('🧨 & close >= 2D centroid', lambda r: r.get('x_squeeze') and not r['below_2D']),
  ('🧨 & close < 2D centroid', lambda r: r.get('x_squeeze') and r['below_2D']),
  ('🧨 & close < all3 centroids', lambda r: r.get('x_squeeze') and r['below_all3']),
  ('🧨 & centroid step_down', lambda r: r.get('x_squeeze') and r['step_down']),
  ('🧨 & not step_down', lambda r: r.get('x_squeeze') and not r['step_down']),
  ('🧨 & close < vol flip', lambda r: r.get('x_squeeze') and r['below_vol_flip']),
  ('🧨 & close >= vol flip', lambda r: r.get('x_squeeze') and not r['below_vol_flip']),
  ('SI>=10% & close >= 2D', lambda r: r['si_ge_10'] and not r['below_2D']),
  ('SI>=10% & close < 2D', lambda r: r['si_ge_10'] and r['below_2D']),
  ('SVR>=55% & close < 2D', lambda r: r['svr_ge_55'] and r['below_2D']),
  ('SVR>=55% & close >= 2D', lambda r: r['svr_ge_55'] and not r['below_2D']),
  ('④派发确认 & IV>RV高位回归', lambda r: r.get('x_direction') in ('派发确认','confirmed trap') and r.get('x_ivrv') == 'IV>RV高位回归'),
  ('④派发确认 & not IV>RV高位回归', lambda r: r.get('x_direction') in ('派发确认','confirmed trap') and r.get('x_ivrv') != 'IV>RV高位回归'),
  ('④派发确认 & close<2D & not IVRV-high', lambda r: r.get('x_direction') in ('派发确认','confirmed trap') and r['below_2D'] and r.get('x_ivrv') != 'IV>RV高位回归'),
  ('step_down & close<2D & not IVRV-high', lambda r: r['step_down'] and r['below_2D'] and r.get('x_ivrv') != 'IV>RV高位回归'),
]
for name, f in tests:
    s = [r for r in recs if f(r)]
    print(f'{name:38s}', '| 1D', m(s, 1), '| 3D', m(s, 3), '| 5D', m(s, 5))
import collections
iv = [r for r in recs if r.get('x_ivrv') == 'IV>RV高位回归']
print('IV>RV高位回归 tickers', collections.Counter(r['ticker'] for r in iv).most_common())
sq = [r for r in recs if r.get('x_squeeze')]
print('🧨 by date: (n, below2D count)', sorted(collections.Counter((r['date'], r['below_2D']) for r in sq).items()))
