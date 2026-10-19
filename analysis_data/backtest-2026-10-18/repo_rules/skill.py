"""Rules specific to the uw-summary / uw-daily-summary skills (claw-stock rules/skills, rules/claude-skill),
tested on the same 368 name-days. Reuses recs.json from cand.py (outcomes + earlier fields)."""
import json, statistics as stt, collections, datetime as dt
WS = '/Users/yuwang/.openclaw/workspace-claw-short'
recs = json.load(open('/tmp/bt_repo_rules/recs.json'))
def brief(d, t):
    return json.load(open(f'{WS}/analysis_data/{"2026-10-16-v1" if d == "2026-10-16" else d}/{t}.json'))
prev = {}
for r in sorted(recs, key=lambda r: r['date']):
    b = brief(r['date'], r['ticker'])
    pdd = (b.get('darkpool_levels') or {}).get('per_day') or {}
    days = sorted(pdd)
    c_today = pdd[days[-1]].get('centroid_top8') if days else None
    c_prev = pdd[days[-2]].get('centroid_top8') if len(days) >= 2 else None
    r['dod_down'] = bool(c_today and c_prev and c_today < c_prev)   # heavy band vs prior day's snapshot
    r['dod_up'] = bool(c_today and c_prev and c_today > c_prev)
    d1 = (((b.get('darkpool_levels') or {}).get('windows') or {}).get('1D') or {}).get('dark_total')
    avg30 = (b.get('screener') or {}).get('avg30_volume')
    r['conf'] = (d1 / avg30) if (d1 and avg30) else None
    ov = sorted(b.get('options_volume_5d') or [], key=lambda x: x['date'])
    if len(ov) >= 5:
        p4 = ov[-5:-1]; t = ov[-1]
        def ratio(k):
            a = stt.mean(x.get(k) or 0 for x in p4)
            return (t.get(k) or 0) / a if a else None
        r['call_ask_x'], r['put_ask_x'] = ratio('call_volume_ask_side'), ratio('put_volume_ask_side')
    else:
        r['call_ask_x'] = r['put_ask_x'] = None
    ne = (b.get('screener') or {}).get('next_earnings_date')
    try:
        r['earn_days'] = (dt.date.fromisoformat(ne[:10]) - dt.date.fromisoformat(r['date'])).days if ne else None
    except ValueError:
        r['earn_days'] = None
    bars = (b.get('price') or {}).get('last_22_bars') or []
    lo = bars[-1][3] if bars else None
    big = [x for x in ((b.get('darkpool') or {}).get('largest') or []) if not x.get('ext_hours')
           and x.get('sale_cond') not in ('average_price_trade', 'prior_reference_price')]
    top = max(big, key=lambda x: x.get('premium') or 0) if big else None
    r['block_at_low'] = bool(top and lo and top['price'] <= lo * 1.01)
    p = prev.get(r['ticker'])
    r['new_break'] = (p is not None and r['below_2D'] and not p['below_2D'])
    r['cont_break'] = (p is not None and r['below_2D'] and p['below_2D'])
    prev[r['ticker']] = r

IVH = lambda r: (not r['rv_gt_iv']) and (r['iv_rank'] or 0) >= 50
crowd = lambda r: r['si_ge_10'] or r['svr_ge_55']
distc = lambda r: r.get('x_direction') in ('派发确认', 'confirmed trap')
r1 = lambda r: bool(r.get('x_squeeze')) and r['below_2D']
r2 = lambda r: r['net_gamma_neg'] and r['below_2D'] and not IVH(r)
r3 = lambda r: crowd(r) and r['below_2D']
dp_leg = lambda r: distc(r) or r.get('x_fingerprint') == '派发'
flow_leg = lambda r: r.get('x_flow') == '偏空' or r['net_put_prem_pos']
r4 = lambda r: (dp_leg(r) or flow_leg(r)) and r['below_2D'] and not IVH(r)
anyr = lambda r: r1(r) or r2(r) or r3(r) or r4(r)
def st(sel, k):
    v = [r for r in sel if r.get(f'r{k}') is not None and r.get(f'e{k}') is not None]
    if not v: return f'{k}D n=0'
    return (f"{k}D n={len(v):3d}({len({r['date'] for r in v}):2d}天{len({r['ticker'] for r in v}):2d}只) 跑输 {sum(r[f'e{k}'] < 0 for r in v) / len(v) * 100:3.0f}% "
            f"超额 {stt.mean(r[f'e{k}'] for r in v) * 100:+5.1f}%")
def show(name, sel): print(f'{name}\n    ' + ' | '.join(st(sel, k) for k in (3, 5)))
B = [r for r in recs if r['below_2D']]; H = [r for r in recs if anyr(r)]
show('对照 v3 命中', H); show('对照 跌破2D', B)
print('\n== 1 置信闸 absDP1d/avg30（skill: <~5% 低可信 → 跳过）')
cs = sorted(r['conf'] for r in recs if r['conf'] is not None)
print('    1D dark / 30日均量 分布: p5 %.2f p25 %.2f 中位 %.2f p75 %.2f, <5%% 的样本 %d' % (cs[len(cs)//20], cs[len(cs)//4], cs[len(cs)//2], cs[3*len(cs)//4], sum(c < .05 for c in cs)))
q = stt.median(r['conf'] for r in H if r['conf'] is not None)
show(f'v3命中 & 暗池量偏低（低于命中组中位 {q:.2f}）', [r for r in H if r['conf'] is not None and r['conf'] < q]); show('v3命中 & 暗池量偏高', [r for r in H if r['conf'] is not None and r['conf'] >= q])
print('\n== 2 跟前一天比的重仓带迁移（skill: 下迁/停滞 = 派发）')
show('当天重心比前一天低 全部', [r for r in recs if r['dod_down']]); show('当天重心比前一天低 & 跌破2D', [r for r in B if r['dod_down']]); show('当天重心比前一天高 & 跌破2D', [r for r in B if r['dod_up']])
show('v3命中 & 当天重心下迁', [r for r in H if r['dod_down']]); show('v3命中 & 当天重心上迁', [r for r in H if r['dod_up']])
print('\n== 3 SI/SVR 高 + 刚跌过 = 拥挤 = squeeze 燃料（skill: 偏多，不是续跌）')
sold = lambda r: (r['ret_5d'] or 0) <= -0.10
show('拥挤 & 5日跌≥10%', [r for r in recs if crowd(r) and sold(r)]); show('拥挤 & 5日跌≥10% & 跌破2D', [r for r in B if crowd(r) and sold(r)])
show('拥挤 & 5日跌<10% & 跌破2D', [r for r in B if crowd(r) and not sold(r)])
print('\n== 4 借券（skill: 费↓+可借↑ = 空头舒服）')
loose = lambda r: r['fee_chg'] is not None and r['fee_chg'] <= 0 and r['avail_chg'] > 0
show('费率不升 & 可借↑ & v3命中', [r for r in H if loose(r)]); show('其余 v3命中', [r for r in H if not loose(r)])
print('\n== 5 Contest day（skill: call / put 两边同时放量 → 不追，等下一天）')
contest = lambda r: (r['call_ask_x'] or 0) >= 1.3 and (r['put_ask_x'] or 0) >= 1.3
show('v3命中 & 两边 ask 量都 ≥1.3x', [r for r in H if contest(r)]); show('v3命中 & 不是', [r for r in H if not contest(r)])
print('\n== 6 刚暴跌 + put 爆量 = 投降 = 燃料（skill: 偏多）')
cap = lambda r: (r['ret_1d'] or 0) <= -0.05 and (r['put_ask_x'] or 0) >= 2
show('当日≤−5% & put ask ≥2x', [r for r in recs if cap(r)]); show('当日≤−5% & put ask <2x', [r for r in recs if (r['ret_1d'] or 0) <= -0.05 and not cap(r)])
print('\n== 7 财报前（skill: 财报前 park）')
show('v3命中 & 7天内财报', [r for r in H if r['earn_days'] is not None and 0 <= r['earn_days'] <= 7]); show('v3命中 & 14天内财报', [r for r in H if r['earn_days'] is not None and 0 <= r['earn_days'] <= 14])
print('\n== 8 趋势仓 > 反转仓（skill: 反转仓 < 趋势仓）')
show('v3命中 & 前一天已在2D下方（趋势延续）', [r for r in H if r['cont_break']]); show('v3命中 & 今天刚跌破（第一天）', [r for r in H if r['new_break']])
print('\n== 9 双源（DP 派发腿 + flow 偏空腿）vs 单源')
show('v3命中 & DP腿和flow腿都有', [r for r in H if dp_leg(r) and flow_leg(r)]); show('v3命中 & 只有DP腿', [r for r in H if dp_leg(r) and not flow_leg(r)])
show('v3命中 & 只有flow腿', [r for r in H if flow_leg(r) and not dp_leg(r)]); show('v3命中 & 两腿都没有（只靠规则1/2/3）', [r for r in H if not dp_leg(r) and not flow_leg(r)])
print('\n== 10 低位吸收块（skill: 低点大单 + 站稳 = 吸收/支撑）')
show('v3命中 & 当天最大一笔暗池在低点1%内', [r for r in H if r['block_at_low']]); show('v3命中 & 不是', [r for r in H if not r['block_at_low']])
