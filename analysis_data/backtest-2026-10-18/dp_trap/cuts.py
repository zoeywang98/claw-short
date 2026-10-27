import sys, io, contextlib
exec(open('/Users/yuwang/.openclaw/workspace-claw-short/analysis_data/backtest-2026-10-18/dp_trap/trap.py').read().split("if __name__ == '__main__':")[0])
exec(open('/Users/yuwang/.openclaw/workspace-claw-short/analysis_data/backtest-2026-10-18/dp_trap/grid.py').read().split("print('grid")[0].split("exec(")[0])
def stat(E, k, direction=-1):
    v = [e for e in E if e.get(f'e{k}') is not None]
    if not v: return '   -   '
    lag = sum(1 for e in v if e[f'e{k}'] * direction > 0) / len(v)
    return f"{lag*100:3.0f}% {st.mean(e[f'e{k}'] for e in v)*100:+5.1f}% n{len(v):3d}"
OPT = {'LITE', 'COHR', 'AAOI', 'GLW', 'AEHR'}
def d2(e):  # depth below TODAY's 2D centroid (v3 浅 measure: (2D - close)/close)
    r = row[(e['T'], e['date'])]; return r['c2D'] / r['close'] - 1
for spec in ((0.05, 0.02, 3), (0.05, 0.0, 1), (0.05, 0.02, 1)):
    with contextlib.redirect_stdout(io.StringIO()):
        P1, P2, HELD, ABOVE_NR, OF = run(*spec, first='2026-07-22')
    print(f'\n== spec R{spec[0]*100:.0f} G{spec[1]*100:.0f} N{spec[2]}  (depth = below today 2D, same as v3 浅)')
    for lab, E in (('P2 all', P2),
                   ('P2 deep >2%', [e for e in P2 if d2(e) > 0.02]), ('P2 shallow ≤2%', [e for e in P2 if 0 < d2(e) <= 0.02]),
                   ('other 1st-day break deep >2%', [e for e in OF if e['depth'] > 0.02]), ('other 1st-day break shallow ≤2%', [e for e in OF if e['depth'] <= 0.02]),
                   ('P2 optics', [e for e in P2 if e['T'] in OPT]), ('P2 ex-optics', [e for e in P2 if e['T'] not in OPT]),
                   ('P2 ex-optics deep >2%', [e for e in P2 if e['T'] not in OPT and d2(e) > 0.02]),
                   ('other 1st-day deep >2% ex-optics', [e for e in OF if e['T'] not in OPT and e['depth'] > 0.02]),
                   ('other 1st-day optics', [e for e in OF if e['T'] in OPT])):
        print(f'{lab:36s} 1D {stat(E,1)} 3D {stat(E,3)} 5D {stat(E,5)}')
# alternative P1 reading: 1W centroid moved < half of the price move since the rally low, close above max(2D,1W)
def run_alt(R=0.05, N=3, first='2026-07-22'):
    P1, P2, seen = [], [], set()
    for T in WL:
        for i in range(3, len(days)):
            r = row.get((T, days[i]))
            if not r or not core(r) or days[i] < first: continue
            js = [j for j in (i - 1, i - 2, i - 3) if row.get((T, days[j])) and row[(T, days[j])]['c1W']]
            if not js: continue
            j0 = min(js, key=lambda j: row[(T, days[j])]['close']); r0 = row[(T, days[j0])]
            dpx = r['close'] - r0['close']
            if r['close'] / r0['close'] - 1 < R or r['close'] <= core(r)[1]: continue
            if (r['c1W'] - r0['c1W']) >= 0.5 * dpx: continue
            lo = core(r)[0]; P1.append(ev(T, i))
            for j in range(i + 1, min(i + N, len(days) - 1) + 1):
                rj = row.get((T, days[j]))
                if rj and rj['close'] < lo:
                    if (T, j) not in seen: seen.add((T, j)); P2.append(ev(T, j))
                    break
    return P1, P2
for N in (1, 3):
    A1, A2 = run_alt(N=N)
    print(f'\nALT (1W moved <50% of price move) N={N}: P1 3D {stat(A1,3)} 5D {stat(A1,5)} | P2 1D {stat(A2,1)} 3D {stat(A2,3)} 5D {stat(A2,5)} | P2 deep>2% 3D {stat([e for e in A2 if d2(e)>0.02],3)} 5D {stat([e for e in A2 if d2(e)>0.02],5)}')
