#!/usr/bin/env python3
"""Old §4.2 "价格负责裁决 DP 的意义" — two outcomes after price moves up into a higher DP area:
  健康 acceptance A : 到达 DP node → 停留 → 回踩守住 → 再向上离开
  失败 / trapped  B : 冲到高位 DP 区 → 无法站稳 → 跌回旧 DP core → 再失守
Setup S (day t): new DP node N = 2D centroid sits ≥b above the old core O = 1W centroid, and price is at/above the node.
Episode tracked for M sessions with N, O fixed at t:
  A at day v: some day u after t has low ≤ N·(1+tol) (回踩) with every close since t ≥ N (守住); then first close > max(close t..v-1) (再向上离开)
  B at day w: first close < O (跌回旧 core 再失守); B_strict also needs an earlier day that closed inside [O, O·(1+tol2)] (跌回旧 core) before losing it
Outcome as in trap.py: close-to-close 1/3/5D vs the 23-name equal-weight average."""
import json, math, statistics as st, collections, sys
P = json.load(open('/Users/yuwang/.openclaw/workspace-claw-short/analysis_data/backtest-2026-10-18/dp_trap/panel.json'))
days, panel = P['days'], P['panel']
WL = list(panel)
row = {(T, r['date']): r for T in WL for r in panel[T]}
def R(T, i): return row.get((T, days[i])) if 0 <= i < len(days) else None
def fwd(T, i, k):
    a, b = R(T, i), R(T, i + k)
    return (b['close'] / a['close'] - 1) if a and b else None
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
def stat(E, k, direction):
    v = [e for e in E if e.get(f'e{k}') is not None]
    if not v: return '     -      '
    hit = sum(1 for e in v if e[f'e{k}'] * direction > 0) / len(v)
    byd = collections.defaultdict(list)
    for e in v: byd[e['date']].append(e[f'e{k}'])
    dm = [sum(x) / len(x) for x in byd.values()]
    td = (st.mean(dm) / (st.pstdev(dm) / math.sqrt(len(dm)))) if len(dm) > 2 and st.pstdev(dm) > 0 else float('nan')
    return f"{hit*100:3.0f}% {st.mean(e[f'e{k}'] for e in v)*100:+5.1f}% raw {st.mean(e[f'r{k}'] for e in v)*100:+5.1f}% n{len(v):3d}/{len(byd):2d}d td{td:+.1f}"
def show(name, E, direction):
    word = 'beat' if direction > 0 else 'lag'
    print(f"{name:46s} {word}  1D {stat(E,1,direction)} | 3D {stat(E,3,direction)} | 5D {stat(E,5,direction)}")

def run(b=0.03, M=10, tol=0.01, tol2=0.02, first='2026-07-22', last=None, quiet=False):
    S, A, B, Bs, NONE = [], [], [], [], []
    for T in WL:
        i = 0
        while i < len(days):
            r = R(T, i)
            ok = r and r['c2D'] and r['c1W'] and days[i] >= first and (not last or days[i] <= last)
            if not ok or not (r['c2D'] >= r['c1W'] * (1 + b) and r['close'] >= r['c2D'] * 0.98):
                i += 1; continue
            N, O = r['c2D'], r['c1W']
            S.append(ev(T, i, N=N, O=O))
            held, touched, hi, at_core, res, j = True, False, r['close'], False, None, i + 1
            while j <= min(i + M, len(days) - 1):
                rj = R(T, j)
                if not rj: j += 1; continue
                if rj['close'] < O:
                    res = ('B', j, at_core); break
                if rj['close'] < N: held = False
                if O <= rj['close'] <= O * (1 + tol2): at_core = True
                if held and rj['low'] <= N * (1 + tol): touched = True
                if held and touched and rj['close'] > hi and not (rj['low'] <= N * (1 + tol) and j == i + 1 and False):
                    res = ('A', j, None); break
                hi = max(hi, rj['close']); j += 1
            if res and res[0] == 'A':
                A.append(ev(T, res[1], setup=days[i], N=N, O=O))
            elif res and res[0] == 'B':
                e = ev(T, res[1], setup=days[i], N=N, O=O, depth=O / R(T, res[1])['close'] - 1)
                B.append(e)
                if res[2]: Bs.append(e)
            else:
                NONE.append(ev(T, min(i + M, len(days) - 1), setup=days[i]))
            i = (res[1] if res else i + M) + 1   # next episode starts after this one resolves / expires
    if not quiet:
        print(f'\n=== b(2D above 1W)≥{b*100:.0f}%  M={M}  retest tol {tol*100:.0f}%  core band {tol2*100:.0f}%  {first}..{last or days[-1]}')
        print(f'episodes {len(S)} | A acceptance {len(A)} | B failure {len(B)} (strict {len(Bs)}) | unresolved {len(NONE)}')
        show('S setup day (price in new higher DP area)', S, -1)
        show('A 健康 acceptance (at leave-up close)', A, +1)
        show('B 失败 trapped (at close < old core)', B, -1)
        show('B strict (touched old core first)', Bs, -1)
    return S, A, B, Bs, NONE

def controls(A, B, first='2026-07-22'):
    akeys = {(e['T'], e['i']) for e in A}; bkeys = {(e['T'], e['i']) for e in B}
    brk, newhi = [], []
    for T in WL:
        for i in range(1, len(days)):
            r, p = R(T, i), R(T, i - 1)
            if not r or not p or days[i] < first or not r['c1W'] or not p['c1W']: continue
            if r['close'] < r['c1W'] and p['close'] >= p['c1W'] and (T, i) not in bkeys:
                brk.append(ev(T, i))
            prev = [R(T, j)['close'] for j in range(max(0, i - 10), i) if R(T, j)]
            if prev and r['close'] > max(prev) and (T, i) not in akeys:
                newhi.append(ev(T, i))
    show('ctrl: first close < 1W centroid, not B', brk, -1)
    show('ctrl: new 10-day closing high, not A', newhi, +1)

if __name__ == '__main__':
    S, A, B, Bs, NONE = run()
    controls(A, B)
    OPT = {'LITE', 'COHR', 'AAOI', 'GLW', 'AEHR'}
    show('A ex-optics', [e for e in A if e['T'] not in OPT], +1); show('B ex-optics', [e for e in B if e['T'] not in OPT], -1)
    show('B deep >2% below old core', [e for e in B if e['depth'] > 0.02], -1); show('B shallow ≤2%', [e for e in B if e['depth'] <= 0.02], -1)
    for lab, a, z in (('Jul22-Aug24', '2026-07-22', '2026-08-24'), ('Aug25-Oct26', '2026-08-25', None)):
        run(first=a, last=z)
    print('\n--- grid (A beat / B lag at 3D and 5D)')
    for b in (0.02, 0.03, 0.05):
        for M in (5, 10):
            for tol in (0.01, 0.02):
                S, A, B, Bs, NONE = run(b=b, M=M, tol=tol, quiet=True)
                print(f'b{b*100:.0f} M{M:2d} tol{tol*100:.0f} | S lag 3D {stat(S,3,-1)[:16]} | A beat 3D {stat(A,3,+1)[:16]} 5D {stat(A,5,+1)[:16]} | B lag 3D {stat(B,3,-1)[:16]} 5D {stat(B,5,-1)[:16]}')
    S, A, B, Bs, NONE = run(quiet=True)
    print('\n--- A events'); [print(f"  {e['date']} {e['T']:5s} setup {e['setup']} node {e['N']:.2f} core {e['O']:.2f} | 3D {e['r3'] and round(e['r3']*100,1)} exc {e['e3'] and round(e['e3']*100,1)} | 5D {e['r5'] and round(e['r5']*100,1)} exc {e['e5'] and round(e['e5']*100,1)}") for e in sorted(A, key=lambda e: e['date'])]
    print('\n--- B events'); [print(f"  {e['date']} {e['T']:5s} setup {e['setup']} node {e['N']:.2f} core {e['O']:.2f} depth {e['depth']*100:.1f}% | 3D {e['r3'] and round(e['r3']*100,1)} exc {e['e3'] and round(e['e3']*100,1)} | 5D {e['r5'] and round(e['r5']*100,1)} exc {e['e5'] and round(e['e5']*100,1)}") for e in sorted(B, key=lambda e: e['date'])]
