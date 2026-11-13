exec(open('/Users/yuwang/.openclaw/workspace-claw-short/analysis_data/backtest-2026-10-18/olivia_core/olivia_bt.py').read().split("for name, sel in S.items():")[0].replace("print('crosscheck", "0 and print('crosscheck"))
S3 = {
 'O1p 放量1.3x & close<当天最密带 & <1M POC': [r for r in base if vs(r) >= 1.3 and r['close'] < r['band_lo'] and r['close'] < r['poc1M']],
 'O1p 对照 ... & >=1M POC': [r for r in base if vs(r) >= 1.3 and r['close'] < r['band_lo'] and r['close'] >= r['poc1M']],
 'O3p close<1D & <1M POC': [r for r in base if r['close'] < r['c1D'] and r['close'] < r['poc1M']],
 'O3p 对照 close<1D & >=1M POC': [r for r in base if r['close'] < r['c1D'] and r['close'] >= r['poc1M']],
 '放量1.3x & close<当天最密带（不看1M）': [r for r in base if vs(r) >= 1.3 and r['close'] < r['band_lo']],
}
for name, sel in S3.items(): summ(name, sel)
OPT = {'LITE', 'COHR', 'AAOI', 'GLW', 'AEHR'}
c = S['O1 但 close>=1M重心（对照）']
summ('对照 光模块', [r for r in c if r['T'] in OPT]); summ('对照 非光模块', [r for r in c if r['T'] not in OPT])
o8 = [r for r in base if vs(r) >= 1.3 and r['c2D'] and r['close'] < r['c2D'] and r['close'] >= r['c1M']]
summ('O8 光模块', [r for r in o8 if r['T'] in OPT]); summ('O8 非光模块', [r for r in o8 if r['T'] not in OPT])
