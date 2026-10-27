import sys, io, contextlib
sys.argv = ['x']
exec(open('/Users/yuwang/.openclaw/workspace-claw-short/analysis_data/backtest-2026-10-18/dp_trap/trap.py').read().split("if __name__ == '__main__':")[0])
def stat(E, k, direction=-1):
    v = [e for e in E if e.get(f'e{k}') is not None]
    if not v: return '   -   '
    lag = sum(1 for e in v if e[f'e{k}'] * direction > 0) / len(v)
    return f"{lag*100:3.0f}% {st.mean(e[f'e{k}'] for e in v)*100:+5.1f}% n{len(v):3d}"
print('grid: P1 (warning day, as short) | P2 (break, as short) | other first-day 2D breaks   — 3D and 5D lag% / mean excess / n')
for R in (0.05, 0.08, 0.10):
    for G in (0.0, 0.02, 0.04):
        for N in (1, 3, 5):
            with contextlib.redirect_stdout(io.StringIO()):
                P1, P2, HELD, ABOVE_NR, OF = run(R, G, N, first='2026-07-22')
            print(f'R{R*100:2.0f} G{G*100:.0f} N{N} | P1 3D {stat(P1,3)} 5D {stat(P1,5)} | P2 3D {stat(P2,3)} 5D {stat(P2,5)} | held(from P1+N, beat) 3D {stat(HELD,3,+1)} | other1st 3D {stat(OF,3)} 5D {stat(OF,5)}')
print()
for lab, a, b in (('Jul22-Aug24 (new backfill)', '2026-07-22', '2026-08-24'), ('Aug25-Oct26', '2026-08-25', '2026-10-26'), ('Sep25-Oct26 (scan period)', '2026-09-25', '2026-10-26')):
    with contextlib.redirect_stdout(io.StringIO()):
        P1, P2, HELD, ABOVE_NR, OF = run(0.05, 0.02, 3, first=a, last=b)
    print(f'{lab:28s} | P1 3D {stat(P1,3)} 5D {stat(P1,5)} | P2 3D {stat(P2,3)} 5D {stat(P2,5)} | held beat 3D {stat(HELD,3,+1)} 5D {stat(HELD,5,+1)} | other1st 3D {stat(OF,3)} 5D {stat(OF,5)}')
with contextlib.redirect_stdout(io.StringIO()):
    P1, P2, HELD, ABOVE_NR, OF = run(0.05, 0.02, 3, first='2026-07-22')
OPT = {'LITE', 'COHR', 'AAOI', 'GLW', 'AEHR'}
print()
for lab, f in (('P2 depth>2% (below P1-day core low)', lambda e: e['depth'] > 0.02), ('P2 depth<=2%', lambda e: e['depth'] <= 0.02),
               ('P2 ex-optics', lambda e: e['T'] not in OPT), ('P2 optics only', lambda e: e['T'] in OPT),
               ('P2 break on day +1', lambda e: e['n_after'] == 1), ('P2 break on day +2/+3', lambda e: e['n_after'] > 1)):
    E = [e for e in P2 if f(e)]
    print(f'{lab:38s} 1D {stat(E,1)} 3D {stat(E,3)} 5D {stat(E,5)}')
# shallow first-day breaks vs 2D (v3 浅 definition: close <2% below today 2D, prev close not below prev 2D)
p2k = {(e['T'], e['i']) for e in P2}
sh = lambda e: e['depth'] <= 0.02
print()
for lab, E in (('first-day 2D break, shallow ≤2%, is P2', [e for e in OF + P2 if (e['T'], e['i']) in p2k]),
               ('first-day 2D break, shallow ≤2%, not P2', [e for e in OF if sh(e)]),
               ('first-day 2D break, deep >2%, not P2', [e for e in OF if not sh(e)])):
    print(f'{lab:44s} 1D {stat(E,1)} 3D {stat(E,3)} 5D {stat(E,5)}')
