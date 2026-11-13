exec(open('/Users/yuwang/.openclaw/workspace-claw-short/analysis_data/backtest-2026-10-18/olivia_core/olivia_bt.py').read().split("for name, sel in S.items():")[0].replace("print('crosscheck", "0 and print('crosscheck"))
S2 = {
 'O6 放量1.3x & close<2D & <1M': [r for r in base if vs(r) >= 1.3 and r['c2D'] and r['close'] < r['c2D'] and r['close'] < r['c1M']],
 'O8 放量1.3x & close<2D & >=1M（对照）': [r for r in base if vs(r) >= 1.3 and r['c2D'] and r['close'] < r['c2D'] and r['close'] >= r['c1M']],
 'O7 close<2D & <1M': [r for r in base if r['c2D'] and r['close'] < r['c2D'] and r['close'] < r['c1M']],
 'O9 close<2D & >=1M（对照）': [r for r in base if r['c2D'] and r['close'] < r['c2D'] and r['close'] >= r['c1M']],
 'O3b close<1D & >=1M（对照）': [r for r in base if r['close'] < r['c1D'] and r['close'] >= r['c1M']],
}
for name, sel in S2.items(): summ(name, sel)
print('--- O1 events'); 
for r in S['O1 放量1.3x & close<当天最密带 & <1M重心']:
    print(' ', r['date'], r['T'], 'ret_d %+.1f%%' % (100*(r['close']/r['pc']-1)), 'vs %.2f' % vs(r), 'x3', None if r['x3'] is None else '%+.1f' % (100*r['x3']))
print('--- contrast events (O1 but >=1M)')
for r in S['O1 但 close>=1M重心（对照）']:
    print(' ', r['date'], r['T'], 'ret_d %+.1f%%' % (100*(r['close']/r['pc']-1)), 'vs %.2f' % vs(r), 'close/1M %+.1f%%' % (100*(r['close']/r['c1M']-1)), 'x3', None if r['x3'] is None else '%+.1f' % (100*r['x3']), 'x5', None if r['x5'] is None else '%+.1f' % (100*r['x5']))
