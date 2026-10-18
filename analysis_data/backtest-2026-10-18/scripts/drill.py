import json, collections
recs = json.load(open('/tmp/bt/joined.json'))
def by(sel, key='date', k=3):
    g = collections.defaultdict(list)
    for r in sel:
        if r.get(f'e{k}') is not None: g[r[key]].append(r[f'e{k}'])
    return {a: (len(v), round(sum(v) / len(v) * 100, 2)) for a, v in sorted(g.items())}
si = [r for r in recs if r['si_ge_10']]
print('SI>=10% tickers', collections.Counter(r['ticker'] for r in si))
print('SI>=10% 3D excess by date', by(si))
print('SI>=10% 3D excess by ticker', by(si, 'ticker'))
sq = [r for r in recs if r.get('x_squeeze')]
print('🧨 tickers', collections.Counter(r['ticker'] for r in sq))
print('🧨 3D excess by date', by(sq))
b2 = [r for r in recs if r['below_2D']]
print('close<2D 3D excess by date', by(b2))
print('close<2D 3D excess by ticker group', by(b2, 'ticker'))
# ex-optics robustness
OPT = {'LITE', 'COHR', 'AAOI', 'GLW', 'AEHR'}
def m(sel, k):
    v = [r[f'e{k}'] for r in sel if r.get(f'e{k}') is not None]
    return (len(v), round(sum(v) / len(v) * 100, 2) if v else None, round(sum(1 for x in v if x < 0) / len(v) * 100) if v else None)
for name, f in [('SI>=10%', lambda r: r['si_ge_10']), ('🧨', lambda r: r.get('x_squeeze')), ('close<2D', lambda r: r['below_2D']),
                ('close<all3', lambda r: r['below_all3']), ('step_down', lambda r: r['step_down']), ('④派发确认', lambda r: r.get('x_direction') in ('派发确认', 'confirmed trap')),
                ('IV>RV高位回归', lambda r: r.get('x_ivrv') == 'IV>RV高位回归'), ('⛔', lambda r: r.get('x_tier') == '⛔'), ('5D higher H/L', lambda r: r['up_5d_structure'])]:
    allr = [r for r in recs if f(r)]; ex = [r for r in allr if r['ticker'] not in OPT]
    print(f'{name:14s} all 1D/3D/5D (n, mean exc %, % below avg):', m(allr, 1), m(allr, 3), m(allr, 5), '| ex-optics:', m(ex, 1), m(ex, 3), m(ex, 5))
# pre-crash only (scans up to 10/07, i.e. before the 10/08-10/16 slide)
pre = [r for r in recs if r['date'] <= '2026-10-07']
for name, f in [('SI>=10%', lambda r: r['si_ge_10']), ('🧨', lambda r: r.get('x_squeeze')), ('close<2D', lambda r: r['below_2D']), ('close<all3', lambda r: r['below_all3']), ('IV>RV高位回归', lambda r: r.get('x_ivrv') == 'IV>RV高位回归')]:
    s = [r for r in pre if f(r)]
    print(f'pre-10/08 {name:12s}', m(s, 1), m(s, 3), m(s, 5))
