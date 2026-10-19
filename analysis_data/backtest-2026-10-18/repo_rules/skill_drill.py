exec(open('/tmp/bt_repo_rules/skill.py').read().split("show('对照 v3 命中', H)")[0])
OPT = {'LITE', 'COHR', 'AAOI', 'GLW', 'AEHR'}
far = lambda r: r['dist2D'] is not None and r['dist2D'] > 0.02
q = stt.median(r['conf'] for r in H if r['conf'] is not None)
heavy = lambda r: r['conf'] is not None and r['conf'] >= q
print('== 趋势延续 vs 第一天跌破，按深度拆')
for nm, f in [('延续', lambda r: r['cont_break']), ('第一天', lambda r: r['new_break'])]:
    show(f'{nm} & 距>2%', [r for r in H if f(r) and far(r)]); show(f'{nm} & 距≤2%', [r for r in H if f(r) and not far(r)])
    show(f'{nm} 去光模块', [r for r in H if f(r) and r['ticker'] not in OPT])
    show(f'{nm} 10/08 前', [r for r in H if f(r) and r['date'] < '2026-10-08']); show(f'{nm} 10/08 起', [r for r in H if f(r) and r['date'] >= '2026-10-08'])
print('\n== 暗池量偏高 vs 偏低，按深度拆')
for nm, f in [('量高', heavy), ('量低', lambda r: r['conf'] is not None and not heavy(r))]:
    show(f'{nm} & 距>2%', [r for r in H if f(r) and far(r)]); show(f'{nm} & 距≤2%', [r for r in H if f(r) and not far(r)])
    show(f'{nm} 去光模块', [r for r in H if f(r) and r['ticker'] not in OPT])
print('\n== 用现成口径：1D 暗池量 ≥ 1M 日均（INSTRUCTIONS 的"放量"）')
show('v3命中 & 放量', [r for r in H if r['dp_vol_ge_1m']]); show('v3命中 & 缩量', [r for r in H if not r['dp_vol_ge_1m']])
show('v3命中 & 放量 & 距≤2%', [r for r in H if r['dp_vol_ge_1m'] and not far(r)]); show('v3命中 & 缩量 & 距≤2%', [r for r in H if not r['dp_vol_ge_1m'] and not far(r)])
print('\n== 延续 和 距>2% 的重叠', sum(1 for r in H if r['cont_break'] and far(r)), '/', sum(1 for r in H if r['cont_break']), '延续里距>2%;', sum(1 for r in H if r['new_break'] and far(r)), '/', sum(1 for r in H if r['new_break']), '第一天里距>2%')
