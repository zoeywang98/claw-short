"""Backtest candidate rules from zoeywang98/claw-stock rules/ on the same 368 scan name-days (9/25-10/16)
as analysis_data/backtest-2026-10-18. Outcomes (r/e 1,3,5 = raw / excess vs 23-name avg) come from joined.json;
signals are recomputed from the briefs the scan read. My thresholds where the repo gives none are marked (mine)."""
import json, os, statistics as stt, collections
WS = '/Users/yuwang/.openclaw/workspace-claw-short'
recs = json.load(open(f'{WS}/analysis_data/backtest-2026-10-18/joined.json'))
GROUP = {}
import sys; sys.path.insert(0, f'{WS}/uw_short_fetch')
from uwsf.watchlist import WATCHLIST
for g in WATCHLIST.values():
    for t in g['tickers']: GROUP[t] = g['label']

def brief(d, t):
    p = f'{WS}/analysis_data/{d}/{t}.json'
    if d == '2026-10-16': p = f'{WS}/analysis_data/2026-10-16-v1/{t}.json'
    return json.load(open(p))

for r in recs:
    b = brief(r['date'], r['ticker'])
    close = r['close']
    ge = (b.get('greek_exposure') or {}); today = ge.get('today') or {}
    ser = ge.get('series_21d') or []
    ng, nd = today.get('net_gamma'), today.get('net_delta')
    gx = b.get('gex_levels') or {}
    vflip = (gx.get('latest') or {}).get('gamma_flip')
    vser = sorted((gx.get('series') or {}).get('vol') or [], key=lambda x: x['date'])
    # F10 three-value regime (vol flip, as our rule 1)
    if close and vflip and ng is not None:
        below = close < vflip
        r['F10'] = ('negG' if ng < 0 else 'shortG') if below else ('transit' if ng < 0 else 'posG')
    else:
        r['F10'] = None
    # spot below vol flip for the last 2 sessions (vol-unwind B 段 "持续 1 trading day")
    bars = {x[0]: x[4] for x in (b.get('price') or {}).get('last_22_bars') or []}
    lastflips = [(x['date'], x.get('gamma_flip')) for x in vser[-2:]]
    r['below_flip_2d'] = len(lastflips) == 2 and all(f and bars.get(d) and bars[d] < f for d, f in lastflips)
    # gamma trend: today vs 5 sessions ago
    gs = [x.get('net_gamma') for x in sorted(ser, key=lambda x: x['date'])]
    r['ng_falling_neg'] = bool(ng is not None and ng < 0 and len(gs) >= 6 and gs[-6] is not None and ng < gs[-6])
    r['ng_cross_neg'] = bool(ng is not None and ng < 0 and len(gs) >= 6 and gs[-6] is not None and gs[-6] >= 0)
    r['dex_pos'] = nd is not None and nd > 0
    r['dex_neg'] = nd is not None and nd < 0
    # |net gamma| percentile inside the 21-day series (repo wants 90D; we only have 21)
    absg = [abs(x) for x in gs if x is not None]
    r['absg_pct'] = (sum(a <= abs(ng) for a in absg) / len(absg)) if (absg and ng is not None) else None
    # borrow: fee and availability vs 5 sessions ago
    sd = sorted(((b.get('short_data') or {}).get('daily_20d') or []), key=lambda x: x['date'])
    if len(sd) >= 6 and sd[-6].get('fee_rate') and sd[-6].get('short_shares_available'):
        f0, f1 = sd[-6]['fee_rate'], sd[-1]['fee_rate']; a0, a1 = sd[-6]['short_shares_available'], sd[-1]['short_shares_available']
        r['fee_chg'] = f1 / f0 - 1; r['avail_chg'] = a1 / a0 - 1
    else:
        r['fee_chg'] = r['avail_chg'] = None
    # SVR dynamics
    sv = sorted(((b.get('short_volume') or {}).get('ratio_20d') or []), key=lambda x: x['market_date'])
    v = [x.get('short_volume_ratio') for x in sv]
    r['svr_d1'] = (v[-1] - v[-2]) if len(v) >= 2 and None not in v[-2:] else None
    r['svr_d3'] = (v[-1] - v[-4]) if len(v) >= 4 and None not in (v[-1], v[-4]) else None
    # SI trend between the last two FINRA settlements, DTC
    sis = sorted(((b.get('short_interest') or {}).get('series') or []), key=lambda x: x['market_date'])
    r['si_chg'] = (sis[-1]['si_float'] / sis[-2]['si_float'] - 1) if len(sis) >= 2 and sis[-2].get('si_float') else None
    r['dtc'] = sis[-1].get('days_to_cover') if sis else None
    # IV rank, ret_1d
    r['ivr'] = (b.get('screener') or {}).get('iv_rank')
    r['ret_1d'] = ((b.get('price') or {}).get('derived') or {}).get('ret_1d')
    # distance below 2D / below 1D centroid
    r['dist2D'] = (r['c2D'] - close) / close if (r['c2D'] and close) else None
    r['below_1D'] = bool(r['c1D'] and close and close < r['c1D'])
    # vol-unwind A 段: in the last 30 sessions, from the low to the later high, did IV30 rise during the rally?
    iv = sorted(((b.get('iv_rv') or {}).get('iv30') or []), key=lambda x: x[0])[-30:]
    r['A_gate'] = None
    if len(iv) >= 20:
        hi_i = max(range(len(iv)), key=lambda i: iv[i][2] or 0)
        lo_i = min(range(0, hi_i + 1), key=lambda i: iv[i][2] or 1e18) if hi_i > 0 else 0
        if hi_i > lo_i and iv[lo_i][2]:
            rally = iv[hi_i][2] / iv[lo_i][2] - 1
            r['A_gate'] = rally >= 0.15 and (iv[hi_i][1] - iv[lo_i][1]) > 0   # (mine) rally >= 15% and IV30 up over it
    r['group'] = GROUP.get(r['ticker'])

# group-level fields on each date
by = collections.defaultdict(list)
for r in recs: by[(r['date'], r['group'])].append(r)
for (d, g), rs in by.items():
    ivrs = [x['ivr'] for x in rs if x['ivr'] is not None]
    med = stt.median(ivrs) if ivrs else None
    sq = sum(1 for x in rs if (x['si_ge_10'] or x['svr_ge_55']) and (x['ret_1d'] or 0) > 0)
    for x in rs:
        x['grp_ivr_med'] = med; x['grp_squeeze_n'] = sq

IVH = lambda r: (not r['rv_gt_iv']) and (r['iv_rank'] or 0) >= 50
crowd = lambda r: r['si_ge_10'] or r['svr_ge_55']
dist = lambda r: r.get('x_direction') in ('派发确认', 'confirmed trap')
r1 = lambda r: bool(r.get('x_squeeze')) and r['below_2D']
r2 = lambda r: r['net_gamma_neg'] and r['below_2D'] and not IVH(r)
r3 = lambda r: crowd(r) and r['below_2D']
r4 = lambda r: (dist(r) or r.get('x_fingerprint') == '派发' or r.get('x_flow') == '偏空' or r['net_put_prem_pos']) and r['below_2D'] and not IVH(r)
anyr = lambda r: r1(r) or r2(r) or r3(r) or r4(r)

def st(sel, k):
    v = [r for r in sel if r.get(f'r{k}') is not None and r.get(f'e{k}') is not None]
    if not v: return f'{k}D n=0'
    return (f"{k}D n={len(v):3d}({len({r['date'] for r in v}):2d}天{len({r['ticker'] for r in v}):2d}只) 跑输 {sum(r[f'e{k}'] < 0 for r in v) / len(v) * 100:3.0f}% "
            f"超额 {stt.mean(r[f'e{k}'] for r in v) * 100:+5.1f}% 涨跌 {stt.mean(r[f'r{k}'] for r in v) * 100:+5.1f}%")
def show(name, sel):
    print(f'{name}\n    ' + ' | '.join(st(sel, k) for k in (3, 5)))

B = [r for r in recs if r['below_2D']]
H = [r for r in recs if anyr(r)]
print('== 对照'); show('全部', recs); show('跌破2D', B); show('v3 任一规则', H); show('跌破2D 没命中规则', [r for r in B if not anyr(r)])

print('\n== F10 三值 regime（spot vs vol flip × net gamma）')
for lab in ('negG', 'shortG', 'posG', 'transit'):
    show(f'{lab} 全部', [r for r in recs if r['F10'] == lab]); show(f'{lab} & 跌破2D', [r for r in B if r['F10'] == lab])
show('规则2 命中 & negG', [r for r in recs if r2(r) and r['F10'] == 'negG']); show('规则2 命中 & 非 negG（spot 在 flip 上方）', [r for r in recs if r2(r) and r['F10'] != 'negG'])
show('v3 命中 & shortG-zone（CANON: 不进空）', [r for r in H if r['F10'] == 'shortG']); show('v3 命中 & 非 shortG', [r for r in H if r['F10'] != 'shortG'])

print('\n== Gamma+DEX 闸（UW net_delta，口径见注）')
for nm, f in [('gamma<0 & net_delta>0', lambda r: r['net_gamma_neg'] and r['dex_pos']), ('gamma<0 & net_delta<0', lambda r: r['net_gamma_neg'] and r['dex_neg']),
              ('gamma 5日内下移且<0', lambda r: r['ng_falling_neg']), ('gamma 5日内由正转负', lambda r: r['ng_cross_neg'])]:
    show(nm + ' 全部', [r for r in recs if f(r)]); show(nm + ' & 跌破2D', [r for r in B if f(r)])

print('\n== 借券（F7 / Fintel 闸）')
for nm, f in [('费率↑ & 可借↓（拥挤，闸=别空）', lambda r: r['fee_chg'] is not None and r['fee_chg'] > 0 and r['avail_chg'] < 0),
              ('费率 5日内 ≥2x（CTB 急升）', lambda r: r['fee_chg'] is not None and r['fee_chg'] >= 1.0),
              ('费率 5日内跌 ≥30%（回补进行中）', lambda r: r['fee_chg'] is not None and r['fee_chg'] <= -0.30),
              ('可借 5日内 −30% 以上（mine）', lambda r: r['avail_chg'] is not None and r['avail_chg'] <= -0.30),
              ('可借 5日内 +50% 以上（mine，空头已回补）', lambda r: r['avail_chg'] is not None and r['avail_chg'] >= 0.50)]:
    show(nm + ' 全部', [r for r in recs if f(r)]); show(nm + ' & v3命中', [r for r in H if f(r)])

print('\n== SVR / SI 相位')
for nm, f in [('F6.5 SVR 3日 +10pt & IVR≥80', lambda r: r['svr_d3'] is not None and r['svr_d3'] >= 0.10 and (r['ivr'] or 0) >= 80),
              ('SVR 3日 +10pt（不看 IVR）', lambda r: r['svr_d3'] is not None and r['svr_d3'] >= 0.10),
              ('相位闸 SVR 单日 −10pt（回补 climax）', lambda r: r['svr_d1'] is not None and r['svr_d1'] <= -0.10),
              ('SI 比上期下降（Fintel: 派发+SI降=危险）', lambda r: r['si_chg'] is not None and r['si_chg'] < 0),
              ('SI 比上期上升', lambda r: r['si_chg'] is not None and r['si_chg'] > 0),
              ('DTC > 5（Fintel: 挤压风险高）', lambda r: (r['dtc'] or 0) > 5)]:
    show(nm + ' 全部', [r for r in recs if f(r)]); show(nm + ' & 跌破2D', [r for r in B if f(r)]); show(nm + ' & v3命中', [r for r in H if f(r)])

print('\n== 价位纪律')
show('跌破2D 超过2%（F1.5 不在 AT-spot 带）', [r for r in B if r['dist2D'] is not None and r['dist2D'] > 0.02])
show('跌破2D 不到2%（F1.5 AT-spot，方向未定）', [r for r in B if r['dist2D'] is not None and r['dist2D'] <= 0.02])
show('v3命中 & 距2D >2%', [r for r in H if r['dist2D'] is not None and r['dist2D'] > 0.02]); show('v3命中 & 距2D ≤2%', [r for r in H if r['dist2D'] is not None and r['dist2D'] <= 0.02])
show('收盘<1D重心（只看最后一天）', [r for r in recs if r['below_1D']]); show('收盘<1D 且 <2D', [r for r in recs if r['below_1D'] and r['below_2D']])
show('收盘<1D 但 ≥2D', [r for r in recs if r['below_1D'] and not r['below_2D']]); show('收盘<2D 但 ≥1D', [r for r in B if not r['below_1D']])

print('\n== 大涨/大跌日（F2.5 / fail_0702）')
show('当日 ≥+5%', [r for r in recs if (r['ret_1d'] or 0) >= 0.05]); show('当日 ≤−5%', [r for r in recs if (r['ret_1d'] or 0) <= -0.05])
show('当日 ≤−5% & 跌破2D', [r for r in B if (r['ret_1d'] or 0) <= -0.05])

print('\n== 板块级（fail_0812 板块 beta 否决 / fail_0702 板块 IVR 警报）')
show('v3命中 & 同组 ≥2 只拥挤票当天上涨（否决闸）', [r for r in H if r['grp_squeeze_n'] >= 2]); show('v3命中 & 同组没有', [r for r in H if r['grp_squeeze_n'] < 2])
show('组内 IVR 中位 ≥80', [r for r in recs if (r['grp_ivr_med'] or 0) >= 80]); show('组内 IVR 中位 ≥60', [r for r in recs if (r['grp_ivr_med'] or 0) >= 60])

print('\n== Vol-unwind（A 段闸 + B 段）')
show('A段闸过（30日内 rally ≥15% 且期间 IV30 上升）', [r for r in recs if r['A_gate']]); show('A段闸过 & 跌破2D', [r for r in B if r['A_gate']])
show('A段闸过 & v3命中', [r for r in H if r['A_gate']]); show('A段闸没过 & v3命中', [r for r in H if r['A_gate'] is False])
show('B段: spot<flip 连2天 & 派发确认/step_down & |gamma| 21日分位≥80', [r for r in recs if r['below_flip_2d'] and (dist(r) or r['step_down']) and (r['absg_pct'] or 0) >= 0.8])
show('spot<flip 连2天 & 跌破2D', [r for r in B if r['below_flip_2d']]); show('spot<flip 连2天 & v3命中', [r for r in H if r['below_flip_2d']]); show('flip 上方或只1天 & v3命中', [r for r in H if not r['below_flip_2d']])
json.dump(recs, open('/tmp/bt_repo_rules/recs.json', 'w'), ensure_ascii=False)
