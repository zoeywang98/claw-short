"""Same as right_wr.py but with accept2.run2 episodes (an episode that first completes a healthy acceptance is not counted as a failure),
so the numbers line up with the 01:29 reply."""
exec(open('/Users/yuwang/.openclaw/workspace-claw-short/analysis_data/backtest-2026-10-18/dp_trap/right_wr.py').read().split("for b in (0.03, 0.02):")[0])
for b in (0.03, 0.02):
    print(f'\n== node 门槛 2D ≥ 1W×{1+b:.2f}')
    for lab, M, f in (('3 天内失守 (M=3)', 3, lambda e: True), ('10 天内任何时候失守', 10, lambda e: True),
                      ('  其中 3 天内', 10, lambda e: e['i'] - idx[e['setup']] <= 3), ('  其中 4–10 天', 10, lambda e: e['i'] - idx[e['setup']] > 3)):
        A, B = run2(b=b, M=M)
        E = [dict(e, O=R(e['T'], idx[e['setup']])['c1W']) for e in B if f(e)]
        print(lab)
        for k in (1, 3, 5): print(f'   {k}D {wr(E, k)}')
        print(f'   持有到收盘站回旧 core / 满 10 天: {hold(E, "old core")}')
        print(f'   持有到收盘站回当天 2D（v3 口径）: {hold(E, "2D")}')
