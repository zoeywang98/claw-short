"""Variants of accept.py: A with an explicit 停留 (retest day strictly before the leave-up day, leave-up ≥2 sessions after setup),
A retesting the OLD core (旧 inventory 被 defend), and fast B (fails within 3 sessions, comparable to trap.py P2)."""
exec(open('/Users/yuwang/.openclaw/workspace-claw-short/analysis_data/backtest-2026-10-18/dp_trap/accept.py').read().split("if __name__ == '__main__':")[0])
def run2(b=0.03, M=10, tol=0.01, node='new', min_v=2, first='2026-07-22'):
    A, B = [], []
    for T in WL:
        i = 0
        while i < len(days):
            r = R(T, i)
            if not (r and r['c2D'] and r['c1W'] and days[i] >= first and r['c2D'] >= r['c1W'] * (1 + b) and r['close'] >= r['c2D'] * 0.98):
                i += 1; continue
            N, O = r['c2D'], r['c1W']
            L = N if node == 'new' else O          # level that must be retested and held
            held, u, hi, res, j = True, None, r['close'], None, i + 1
            while j <= min(i + M, len(days) - 1):
                rj = R(T, j)
                if not rj: j += 1; continue
                if rj['close'] < O: res = ('B', j); break
                if rj['close'] < L: held = False
                if held and u is not None and j > u and j - i >= min_v and rj['close'] > hi: res = ('A', j); break
                if held and u is None and rj['low'] <= L * (1 + tol): u = j
                hi = max(hi, rj['close']); j += 1
            if res: (A if res[0] == 'A' else B).append(ev(T, res[1], setup=days[i]))
            i = (res[1] if res else i + M) + 1
    return A, B
print('A = beat rate (expect high); B = lag rate (expect high)')
for node in ('new', 'old'):
    for b in (0.02, 0.03, 0.05):
        for M in (3, 5, 10):
            A, B = run2(b=b, M=M, node=node)
            print(f'retest {node:3s} node | b{b*100:.0f} M{M:2d} | A 3D {stat(A,3,+1)[:16]} 5D {stat(A,5,+1)[:16]} | B 3D {stat(B,3,-1)[:16]} 5D {stat(B,5,-1)[:16]}')
A, B = run2()
print()
show('A main (retest new node, 停留≥2d)', A, +1)
show('B main', B, -1)
A, B = run2(node='old')
show('A retest OLD core (旧 inventory 被 defend)', A, +1)
