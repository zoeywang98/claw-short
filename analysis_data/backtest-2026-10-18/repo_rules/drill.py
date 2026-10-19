import json, statistics as stt, collections
recs = json.load(open('/tmp/bt_repo_rules/recs.json'))
IVH = lambda r: (not r['rv_gt_iv']) and (r['iv_rank'] or 0) >= 50
crowd = lambda r: r['si_ge_10'] or r['svr_ge_55']
dist = lambda r: r.get('x_direction') in ('派发确认', 'confirmed trap')
r1 = lambda r: bool(r.get('x_squeeze')) and r['below_2D']
r2 = lambda r: r['net_gamma_neg'] and r['below_2D'] and not IVH(r)
r3 = lambda r: crowd(r) and r['below_2D']
r4 = lambda r: (dist(r) or r.get('x_fingerprint') == '派发' or r.get('x_flow') == '偏空' or r['net_put_prem_pos']) and r['below_2D'] and not IVH(r)
anyr = lambda r: r1(r) or r2(r) or r3(r) or r4(r)
OPT = {'LITE', 'COHR', 'AAOI', 'GLW', 'AEHR'}
def st(sel, k):
    v = [r for r in sel if r.get(f'r{k}') is not None and r.get(f'e{k}') is not None]
    if not v: return f'{k}D n=0'
    return (f"{k}D n={len(v):3d}({len({r['date'] for r in v}):2d}天{len({r['ticker'] for r in v}):2d}只) 跑输 {sum(r[f'e{k}'] < 0 for r in v) / len(v) * 100:3.0f}% "
            f"超额 {stt.mean(r[f'e{k}'] for r in v) * 100:+5.1f}%")
def show(name, sel): print(f'{name}\n    ' + ' | '.join(st(sel, k) for k in (1, 3, 5)))
B = [r for r in recs if r['below_2D']]; H = [r for r in recs if anyr(r)]
print('== 距 2D 重心阈值扫描（跌破的票）')
for lo, hi in ((0, .005), (.005, .01), (.01, .02), (.02, .03), (.03, 1)):
    show(f'跌破 {lo*100:.1f}–{hi*100:.1f}%', [r for r in B if r['dist2D'] is not None and lo < r['dist2D'] <= hi])
crash = lambda r: (r['ret_1d'] or 0) <= -0.05
far = lambda r: r['dist2D'] is not None and r['dist2D'] > 0.02
print('\n== 距 >2% vs 当天大跌 交叉')
show('距>2% 且当日≤−5%', [r for r in B if far(r) and crash(r)]); show('距>2% 当日>−5%', [r for r in B if far(r) and not crash(r)])
show('距≤2% 且当日≤−5%', [r for r in B if not far(r) and crash(r)]); show('距≤2% 当日>−5%', [r for r in B if not far(r) and not crash(r)])
print('\n== 去掉光模块 / 分前后半段')
for nm, f in [('距>2%', far), ('距≤2%', lambda r: not far(r))]:
    show(nm + ' 去光模块', [r for r in B if f(r) and r['ticker'] not in OPT])
    show(nm + ' 10/08 前', [r for r in B if f(r) and r['date'] < '2026-10-08']); show(nm + ' 10/08 起', [r for r in B if f(r) and r['date'] >= '2026-10-08'])
print('距>2% 的样本:', sorted((r['date'][5:], r['ticker'], round(r['dist2D'] * 100, 1)) for r in B if far(r)))
gd = lambda r: r['net_gamma_neg'] and r['dex_pos']
print('\n== Gamma<0 & net_delta>0（跌破2D）稳健性')
show('去光模块', [r for r in B if gd(r) and r['ticker'] not in OPT]); show('且距≤2%', [r for r in B if gd(r) and not far(r)])
show('规则2 命中 & net_delta>0', [r for r in recs if r2(r) and r['dex_pos']]); show('规则2 命中 & net_delta<0', [r for r in recs if r2(r) and r['dex_neg']])
print('样本:', sorted((r['date'][5:], r['ticker']) for r in B if gd(r)))
print('net_delta<0 样本:', sorted((r['date'][5:], r['ticker']) for r in B if r['net_gamma_neg'] and r['dex_neg']))
A = lambda r: r['A_gate']
print('\n== A 段闸 稳健性（v3 命中）')
show('A过 去光模块', [r for r in H if A(r) and r['ticker'] not in OPT]); show('A没过 去光模块', [r for r in H if A(r) is False and r['ticker'] not in OPT])
show('A过 且距≤2%', [r for r in H if A(r) and not far(r)]); show('A没过 且距≤2%', [r for r in H if A(r) is False and not far(r)])
show('A过 10/08 前', [r for r in H if A(r) and r['date'] < '2026-10-08']); show('A过 10/08 起', [r for r in H if A(r) and r['date'] >= '2026-10-08'])
show('A没过 10/08 前', [r for r in H if A(r) is False and r['date'] < '2026-10-08']); show('A没过 10/08 起', [r for r in H if A(r) is False and r['date'] >= '2026-10-08'])
print('A过 v3命中 票:', collections.Counter(r['ticker'] for r in H if A(r)).most_common())
print('A没过 v3命中 票:', collections.Counter(r['ticker'] for r in H if A(r) is False).most_common())
print('\n== 合起来: v3 命中里 (距>2% 或 A段闸) vs 都不满足')
show('满足其一', [r for r in H if far(r) or A(r)]); show('都不满足', [r for r in H if not far(r) and not A(r)])
