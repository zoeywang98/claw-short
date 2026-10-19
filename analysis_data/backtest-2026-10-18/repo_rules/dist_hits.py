import json, statistics as stt
exec(open('/tmp/bt_repo_rules/drill.py').read().split("B = [r for r in recs")[0])
H = [r for r in recs if anyr(r)]
for lo, hi in ((0, .01), (.01, .02), (.02, 1)):
    show(f'v3命中 跌破2D {lo*100:.0f}–{hi*100:.0f}%', [r for r in H if r['dist2D'] is not None and lo < r['dist2D'] <= hi])
WS = '/Users/yuwang/.openclaw/workspace-claw-short'
print('10/16 v3 (fresh briefs):')
for T in 'LITE COHR AAOI GLW AEHR VRT NBIS DELL MSFT NOW MDB RVMD VKTX'.split():
    b = json.load(open(f'{WS}/analysis_data/2026-10-16/{T}.json'))
    c = b['price']['derived']['close']; c2 = b['darkpool_levels']['windows']['2D']['centroid_top8']
    print(f'  {T:5} close {c} 2D {c2:.2f} below {(c2 - c) / c * 100:.1f}%')
