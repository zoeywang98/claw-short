import sys
sys.path.insert(0, '/Users/yuwang/.openclaw/workspace-claw-short/analysis_data/backtest-2026-10-18/rulebook_all')
import rules as B
from rules import row, ret, doi, near, heavy, step_down, svr_consec, iv_dn, call_bid_dom, stats, R, WL, ROWS, FIRST

def below(r): return r['close'] < r['c2D']
def ivh(r): return r['iv30'] > r['rv21'] and (r.get('iv_rank') or 0) >= 0.5
def dtc_ok(r):
    if (r.get('dtc') or 99) <= 2: return True
    h = r.get('dtc_hist')
    return isinstance(h, list) and len(h) >= 3 and h[-3] < h[-2] < h[-1]
def r1(T, d, r): return ((r.get('si_float') or 0) >= 0.10 or svr_consec(T, d)) and dtc_ok(r) and near(r['close'], r['flip'], 0.03) and below(r)
def r2(T, d, r): return r['net_gamma'] < 0 and below(r) and not ivh(r)
def r3(T, d, r): return ((r.get('si_float') or 0) >= 0.10 or (r.get('svr') or 0) >= 0.55) and below(r)
def fp(T, d, r): return heavy(r) and r['c2D'] <= r['c1W'] and ret(T, d, 5) <= 0.01 and (doi(T, d, 'call', 3) <= 0 or doi(T, d, 'put', 3) > 0) and iv_dn(T, d)
def flow_bear(r): return r['put_volume_ask_side'] > r['put_volume_bid_side'] and call_bid_dom(r)
def r4(T, d, r): return (step_down(r) or fp(T, d, r) or flow_bear(r) or r['net_put_premium'] > 0) and below(r) and not ivh(r)
def anyr(T, d, r): return any(f(T, d, r) for f in (r1, r2, r3, r4))
def norule(T, d, r): return below(r) and not anyr(T, d, r)
def ran15(T, d, r): return ret(T, d, 5) >= 0.15
def ivh_avoid(T, d, r): return ivh(r)
CHT = [f for (_, name, _, _, f) in B.RULES if name.startswith('近似版 Day 2')][0]

TESTS = [('规则1 🧨+<2D', r1, 'bear'), ('规则2 负gamma+<2D', r2, 'bear'), ('规则3 拥挤+<2D', r3, 'bear'),
         ('规则4 派发+<2D', r4, 'bear'), ('任一规则', anyr, 'bear'), ('<2D 没规则', norule, 'bear'),
         ('<2D 单看', lambda T, d, r: below(r), 'bear'),
         ('IV>RV高位 别空', ivh_avoid, 'bull'), ('CHT 近似', CHT, 'bear'), ('刚急涨5日≥15% 当空', ran15, 'bear')]
def ev(fn, lo, hi):
    out = []
    for T in WL:
        for r in ROWS[T]:
            d = r['date']
            if d < lo or d > hi: continue
            try:
                if fn(T, d, r): out.append((T, d))
            except (TypeError, ZeroDivisionError, KeyError): pass
    return out
def f(s): return '   -' if not s else f"{s['hit']*100:3.0f}% {s['exc']*100:+5.1f}% n{s['n']:3d} t{s['td']:+.1f}"
for name, fn, dr in TESTS:
    line = f'{name:18s}'
    for lab, lo, hi in (('全', FIRST, '2026-12-31'), ('7/22-9/24', FIRST, '2026-09-24'), ('9/25+', '2026-09-25', '2026-12-31')):
        e = ev(fn, lo, hi)
        line += f" | {lab} 3D {f(stats(e, dr, 3))} 5D {f(stats(e, dr, 5))}"
    print(line)
