#!/usr/bin/env python3
"""Backtest of the two §4.2 patterns (old rulebook COHR 8/17–8/18 case):
P1 trap warning  = strong rally, price runs ahead of the 1W/2D DP centroids (DP non-confirmation)
P2 confirmed trap = within N sessions after P1, close falls below the shared core (min of the P1-day 2D/1W centroids)
Outcome = close-to-close 1/3/5-day return; 'lag' = underperformed the 23-name equal-weight average (same as the 10/18 backtest)."""
import json, math, statistics as st, collections, sys
P = json.load(open('/Users/yuwang/.openclaw/workspace-claw-short/analysis_data/backtest-2026-10-18/dp_trap/panel.json'))
days, panel = P['days'], P['panel']
WL = list(panel)
idx = {d: i for i, d in enumerate(days)}
row = {(T, r['date']): r for T in WL for r in panel[T]}
def close(T, i): r = row.get((T, days[i])) if 0 <= i < len(days) else None; return r and r['close']
def fwd(T, i, k): a, b = close(T, i), close(T, i + k); return (b / a - 1) if a and b else None
avg = {}
for i in range(len(days)):
    for k in (1, 3, 5):
        v = [x for x in (fwd(T, i, k) for T in WL) if x is not None]
        avg[(i, k)] = sum(v) / len(v) if len(v) >= 15 else None
def ev(T, i, **kw):
    e = {'T': T, 'i': i, 'date': days[i], **kw}
    for k in (1, 3, 5):
        f = fwd(T, i, k); e[f'r{k}'] = f
        e[f'e{k}'] = f - avg[(i, k)] if f is not None and avg[(i, k)] is not None else None
    return e
def show(name, E, direction=-1):
    out = [f'{name:44s}']
    for k in (1, 3, 5):
        v = [e for e in E if e[f'e{k}'] is not None]
        if not v: out.append(f'{k}D -'); continue
        ex = [e[f'e{k}'] for e in v]; raw = [e[f'r{k}'] for e in v]
        byd = collections.defaultdict(list)
        for e in v: byd[e['date']].append(e[f'e{k}'])
        dm = [sum(x) / len(x) for x in byd.values()]
        td = (st.mean(dm) / (st.pstdev(dm) / math.sqrt(len(dm)))) if len(dm) > 2 and st.pstdev(dm) > 0 else float('nan')
        lag = sum(1 for x in ex if x * direction > 0) / len(ex)
        out.append(f"{k}D n={len(v):3d}/{len(byd):2d}d/{len(set(e['T'] for e in v)):2d}T raw {st.mean(raw)*100:+5.1f}% exc {st.mean(ex)*100:+5.1f}% {'lag' if direction<0 else 'beat'} {lag*100:3.0f}% td {td:+.1f}")
    print('  '.join(out))
def core(r): return (min(r['c2D'], r['c1W']), max(r['c2D'], r['c1W'])) if r['c2D'] and r['c1W'] else None
def rally(T, i):
    prev = [close(T, j) for j in (i - 1, i - 2, i - 3)]
    prev = [x for x in prev if x]
    return close(T, i) / min(prev) - 1 if prev and close(T, i) else None

def run(R, G, N, first=None, last=None, label='', verbose=False):
    P1, P2, HELD, CTRL_BRK, ALLBRK_FIRST, ABOVE_NR = [], [], [], [], [], []
    seen_brk = set()
    for T in WL:
        for i in range(len(days)):
            r = row.get((T, days[i]))
            if not r or not core(r) or (first and days[i] < first) or (last and days[i] > last): continue
            lo, hi = core(r); c = r['close']; ra = rally(T, i)
            gap = c / hi - 1
            # generic first-day break below 2D (v3 precondition, prev close not below its own 2D)
            rp = row.get((T, days[i - 1])) if i else None
            if rp and rp['c2D'] and r['c2D'] and c < r['c2D'] and rp['close'] >= rp['c2D']:
                ALLBRK_FIRST.append(ev(T, i, depth=r['c2D'] / c - 1))
            if ra is None or gap < G: continue
            if ra < R:
                ABOVE_NR.append(ev(T, i)); continue
            e1 = ev(T, i, gap=gap, rally=ra, lo=lo, hi=hi)
            P1.append(e1)
            brk = None
            for j in range(i + 1, min(i + N, len(days) - 1) + 1):
                rj = row.get((T, days[j]))
                if rj and rj['close'] < lo: brk = j; break
            e1['broke'] = brk is not None
            if brk is not None:
                if (T, brk) not in seen_brk:
                    seen_brk.add((T, brk))
                    rb = row[(T, days[brk])]
                    nxt = row.get((T, days[brk + 1])) if brk + 1 < len(days) else None
                    P2.append(ev(T, brk, p1=days[i], lo=lo, depth=lo / rb['close'] - 1,
                                 below2D_today=bool(rb['c2D'] and rb['close'] < rb['c2D']),
                                 reclaim_next=(nxt['close'] >= lo) if nxt else None, n_after=brk - i))
            elif i + N < len(days):
                HELD.append(ev(T, i + N, p1=days[i]))
    p2keys = {(e['T'], e['i']) for e in P2}
    other_first = [e for e in ALLBRK_FIRST if (e['T'], e['i']) not in p2keys]
    print(f'\n=== R(rally)≥{R*100:.0f}%  G(close above max(2D,1W))≥{G*100:.0f}%  N={N}  {label}')
    show('P1 trap warning, at P1 close (as short)', P1)
    show('P1 → broke core within N: P1-day close', [e for e in P1 if e['broke']])
    show('P1 → held N days: P1-day close', [e for e in P1 if not e['broke']])
    show('P2 confirmed trap, at break close', P2)
    show('  P2 & next day did not reclaim core (from next)', [ev(e['T'], e['i'] + 1) for e in P2 if e['reclaim_next'] is False])
    show('  P2 & next day reclaimed core (from next)', [ev(e['T'], e['i'] + 1) for e in P2 if e['reclaim_next'] is True])
    show('Held N days, from day P1+N (expect up)', HELD, +1)
    show('control: above core≥G, no strong rally', ABOVE_NR)
    show('control: first-day break <2D, not P2', other_first)
    show('control: first-day break <2D, all', ALLBRK_FIRST)
    nb = sum(1 for e in P1 if e['broke'])
    print(f'P1 days {len(P1)} | broke within {N}: {nb} ({nb/max(1,len(P1))*100:.0f}%) | P2 events {len(P2)}')
    if verbose:
        for e in sorted(P2, key=lambda e: (e['date'], e['T'])):
            print(f"   P2 {e['date']} {e['T']:5s} warn {e['p1']} +{e['n_after']}d depth {e['depth']*100:4.1f}% below2D {e['below2D_today']} reclaim_next {e['reclaim_next']} | 1D {fmtp(e['r1'])} 3D {fmtp(e['r3'])} 5D {fmtp(e['r5'])} | exc3 {fmtp(e['e3'])} exc5 {fmtp(e['e5'])}")
    return P1, P2, HELD, ABOVE_NR, other_first
def fmtp(x): return '  -  ' if x is None else f'{x*100:+5.1f}%'
if __name__ == '__main__':
    run(0.05, 0.02, 3, first='2026-07-22', verbose=True)
