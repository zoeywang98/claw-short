#!/usr/bin/env python3
import json, math, statistics as st, collections
prices = json.load(open('/tmp/bt/prices.json'))
ext = {r['id']: r for r in json.load(open('/tmp/bt/extracted.json'))}
sig = {f"{r['date']}|{r['ticker']}": r for r in json.load(open('/tmp/bt/signals.json'))}
WL = [t for t in prices if t not in ('SPY', 'SMH', 'QQQ')]
days = sorted(prices['SPY'])

def fwd(T, d, k):
    s = prices[T]
    if d not in s: return None
    i = days.index(d)
    if i + k >= len(days): return None
    d2 = days[i + k]
    return s[d2][3] / s[d][3] - 1 if d2 in s else None

avg = {}
for d in days:
    for k in (1, 3, 5):
        v = [fwd(T, d, k) for T in WL]
        v = [x for x in v if x is not None]
        avg[(d, k)] = sum(v) / len(v) if len(v) >= 15 else None

recs = []
for key, s in sig.items():
    d, T = key.split('|')
    e = ext.get(key, {})
    r = {**s, **{f'x_{k}': v for k, v in e.items()}}
    for k in (1, 3, 5):
        f = fwd(T, d, k)
        r[f'r{k}'] = f
        r[f'e{k}'] = (f - avg[(d, k)]) if (f is not None and avg.get((d, k)) is not None) else None
    recs.append(r)
json.dump(recs, open('/tmp/bt/joined.json', 'w'), ensure_ascii=False)

def stats(sel, direction, k):
    """direction -1 = bearish call (right if return < 0), +1 = bullish."""
    v = [r for r in sel if r.get(f'r{k}') is not None]
    if not v: return None
    raw = [r[f'r{k}'] for r in v]; exc = [r[f'e{k}'] for r in v if r.get(f'e{k}') is not None]
    hit = sum(1 for x in raw if x * direction > 0) / len(raw)
    hitx = sum(1 for x in exc if x * direction > 0) / len(exc) if exc else None
    mx = sum(exc) / len(exc) if exc else None
    t = (mx / (st.pstdev(exc) / math.sqrt(len(exc)))) if exc and len(exc) > 2 and st.pstdev(exc) > 0 else None
    # date-clustered: average excess per date, t across dates
    byd = collections.defaultdict(list)
    for r in v:
        if r.get(f'e{k}') is not None: byd[r['date']].append(r[f'e{k}'])
    dm = [sum(x) / len(x) for x in byd.values()]
    tdate = (sum(dm) / len(dm)) / (st.pstdev(dm) / math.sqrt(len(dm))) if len(dm) > 2 and st.pstdev(dm) > 0 else None
    return {'n': len(v), 'ndays': len(byd), 'mean_raw': sum(raw) / len(raw), 'hit_raw': hit, 'mean_exc': mx, 'hit_exc': hitx, 't': t, 't_date': tdate}

def fmt(name, sel, direction):
    out = [name]
    for k in (1, 3, 5):
        s = stats(sel, direction, k)
        if not s: out.append(f'{k}D: -'); continue
        out.append(f"{k}D n={s['n']}/{s['ndays']}d raw {s['mean_raw']*100:+.2f}% hit {s['hit_raw']*100:.0f}% | exc {s['mean_exc']*100:+.2f}% hit {s['hit_exc']*100:.0f}% t={'-' if s['t'] is None else round(s['t'],1)} td={'-' if s['t_date'] is None else round(s['t_date'],1)}")
    return '  '.join(out)

B, U = -1, 1
tests = [
    ('ALL (base, as bearish)', lambda r: True, B),
    # tiers
    ('tier ✅低', lambda r: r.get('x_tier') == '✅低', B),
    ('tier 👀', lambda r: r.get('x_tier') == '👀', B),
    ('tier ⚪', lambda r: r.get('x_tier') == '⚪', B),
    ('tier ⛔', lambda r: r.get('x_tier') == '⛔', B),
    ('tier 🧨 (expect up)', lambda r: r.get('x_tier') == '🧨', U),
    # ④ direction readings (adopted or not)
    ('④ 派发确认', lambda r: r.get('x_direction') == '派发确认', B),
    ('④ confirmed trap', lambda r: r.get('x_direction') == 'confirmed trap', B),
    ('④ Trap warning', lambda r: r.get('x_direction') == 'Trap warning', B),
    ('④ 派发确认+trap', lambda r: r.get('x_direction') in ('派发确认', 'confirmed trap'), B),
    ('④ 吸筹确认 (expect up)', lambda r: r.get('x_direction') == '吸筹确认', U),
    ('④ 不明', lambda r: r.get('x_direction') == '不明', B),
    ('④ 派发确认 & breaker', lambda r: r.get('x_direction') in ('派发确认', 'confirmed trap') and r.get('x_breaker'), B),
    ('④ 派发确认 & no breaker', lambda r: r.get('x_direction') in ('派发确认', 'confirmed trap') and not r.get('x_breaker'), B),
    ('④ 派发确认 & backlash flag', lambda r: r.get('x_direction') in ('派发确认', 'confirmed trap') and r.get('x_backlash'), B),
    ('④ 派发确认 & no backlash', lambda r: r.get('x_direction') in ('派发确认', 'confirmed trap') and not r.get('x_backlash'), B),
    ('④ 派发确认 & 🧨', lambda r: r.get('x_direction') in ('派发确认', 'confirmed trap') and r.get('x_squeeze'), B),
    ('④ 派发确认 & not 🧨', lambda r: r.get('x_direction') in ('派发确认', 'confirmed trap') and not r.get('x_squeeze'), B),
    ('④ 派发确认 & sector veto', lambda r: r.get('x_direction') in ('派发确认', 'confirmed trap') and r.get('x_sector_veto'), B),
    ('④ 派发确认 & THIN', lambda r: r.get('x_direction') in ('派发确认', 'confirmed trap') and r.get('x_thin') is True, B),
    # 🧨 components
    ('🧨 squeeze (expect up)', lambda r: r.get('x_squeeze'), U),
    ('breaker day (as bearish)', lambda r: r.get('x_breaker'), B),
    # ⑤ fingerprints
    ('⑤ 派发', lambda r: r.get('x_fingerprint') == '派发', B),
    ('⑤ 吸货 (expect up)', lambda r: r.get('x_fingerprint') == '吸货', U),
    ('⑤ 库存转移 (expect up)', lambda r: r.get('x_fingerprint') == '库存转移', U),
    ('⑤ Gamma hedge', lambda r: r.get('x_fingerprint') == 'Gamma hedge', B),
    # IV x RV
    ('IVRV RV>IV空头行情+顶部机制', lambda r: r.get('x_ivrv') in ('RV>IV空头行情', '顶部机制'), B),
    ('IVRV RV>IV低位多头 (expect up)', lambda r: r.get('x_ivrv') == 'RV>IV低位多头', U),
    ('IVRV IV>RV高位回归', lambda r: r.get('x_ivrv') == 'IV>RV高位回归', B),
    ('IVRV bounce相位 (expect up)', lambda r: r.get('x_ivrv') == 'bounce相位', U),
    # ⑥ dealer & flow
    ('⑥ dealer 卖股票', lambda r: r.get('x_dealer_stock') == '卖', B),
    ('⑥ dealer 买股票 (expect up)', lambda r: r.get('x_dealer_stock') == '买', U),
    ('flow 偏空', lambda r: r.get('x_flow') == '偏空', B),
    ('flow 偏多 (expect up)', lambda r: r.get('x_flow') == '偏多', U),
    # raw signals from briefs
    ('RAW centroid step_down 1M>1W>2D', lambda r: r['step_down'], B),
    ('RAW centroid step_up (expect up)', lambda r: r['step_up'], U),
    ('RAW close < 2D centroid', lambda r: r['below_2D'], B),
    ('RAW close < 1D,2D,1W centroids', lambda r: r['below_all3'], B),
    ('RAW close > 1D,2D,1W (expect up)', lambda r: r['above_all3'], U),
    ('RAW step_down & close<all3', lambda r: r['step_down'] and r['below_all3'], B),
    ('RAW step_down & close<2D', lambda r: r['step_down'] and r['below_2D'], B),
    ('RAW step_down & net gamma<0', lambda r: r['step_down'] and r['net_gamma_neg'], B),
    ('RAW step_down & close<vol flip', lambda r: r['step_down'] and r['below_vol_flip'], B),
    ('RAW step_down & 5D lower highs/lows', lambda r: r['step_down'] and r['down_5d_structure'], B),
    ('RAW net gamma < 0', lambda r: r['net_gamma_neg'], B),
    ('RAW close < vol flip', lambda r: r['below_vol_flip'], B),
    ('RAW close < OI flip', lambda r: r['below_oi_flip'], B),
    ('RAW RV21 > IV30', lambda r: r['rv_gt_iv'], B),
    ('RAW RV>IV & IV rank>=50', lambda r: r['rv_gt_iv'] and (r['iv_rank'] or 0) >= 50, B),
    ('RAW RV>IV & IV rank<30 (expect up)', lambda r: r['rv_gt_iv'] and (r['iv_rank'] or 100) < 30, U),
    ('RAW net call premium < 0 (calls sold)', lambda r: r['net_call_prem_neg'], B),
    ('RAW net put premium > 0 (puts bought)', lambda r: r['net_put_prem_pos'], B),
    ('RAW calls sold & puts bought', lambda r: r['net_call_prem_neg'] and r['net_put_prem_pos'], B),
    ('RAW SI >= 10% (expect up)', lambda r: r['si_ge_10'], U),
    ('RAW SVR >= 55%', lambda r: r['svr_ge_55'], B),
    ('RAW block participation >= 16%', lambda r: r['block_ge_16'], B),
    ('RAW 5D lower highs & lows', lambda r: r['down_5d_structure'], B),
    ('RAW 5D higher highs & lows (expect up)', lambda r: r['up_5d_structure'], U),
]
for name, f, direction in tests:
    print(fmt(name, [r for r in recs if f(r)], direction))
