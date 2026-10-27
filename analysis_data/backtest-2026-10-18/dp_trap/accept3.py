exec(open('/Users/yuwang/.openclaw/workspace-claw-short/analysis_data/backtest-2026-10-18/dp_trap/accept2.py').read().split("print('A = beat")[0])
OPT = {'LITE', 'COHR', 'AAOI', 'GLW', 'AEHR'}
for b in (0.02, 0.03, 0.05):
    for M in (3, 10):
        A, B = run2(b=b, M=M)
        print(f'b{b*100:.0f} M{M:2d}')
        show('   A acceptance (retest new node held, 停留)', A, +1)
        show('   B trapped (close < old core)', B, -1)
# fast-failure split: B events that came within 3 sessions vs 4–10 sessions after the setup (b3, M10)
A, B = run2(b=0.03, M=10)
idx = {d: i for i, d in enumerate(days)}
fast = [e for e in B if e['i'] - idx[e['setup']] <= 3]; slow = [e for e in B if e['i'] - idx[e['setup']] > 3]
print('\nb3 M10 split by time to failure')
show('   B fails within 3 sessions', fast, -1); show('   B fails after 4–10 sessions', slow, -1)
show('   B fast, optics', [e for e in fast if e['T'] in OPT], -1); show('   B fast, ex-optics', [e for e in fast if e['T'] not in OPT], -1)
A2, B2 = run2(b=0.02, M=10)
fast2 = [e for e in B2 if e['i'] - idx[e['setup']] <= 3]
show('   (b2) B fast, optics', [e for e in fast2 if e['T'] in OPT], -1); show('   (b2) B fast, ex-optics', [e for e in fast2 if e['T'] not in OPT], -1)
