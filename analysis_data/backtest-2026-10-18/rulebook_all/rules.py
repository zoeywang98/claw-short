#!/usr/bin/env python3
"""Full-rulebook backtest (ZZ 2026-10-27 "回测rulebook里的所有rule"): every rule in RULEBOOK.pdf (+ DP 灰色重心迁移法 + Dealer
Hedging guide) that UW data can express, as a mechanical event on the daily feature table (features.json, 7/22 .. last close).
Thresholds the documents leave open are mine and listed in THRESH below. Outcome = close-to-close 1/3/5 sessions;
bear rules score 'lag' (excess vs the 23-name equal-weight average < 0), bull rules 'beat' (> 0); 'abs' = raw return in the
rule's direction. 'none' rules claim no direction: they pass when both hit rates stay near 50%."""
import json, math, statistics as st, collections, datetime as dt, sys
F = json.load(open('/private/tmp/bt_all/features.json'))
DAYS = F['days']; IDX = {d: i for i, d in enumerate(DAYS)}
ROWS = F['rows']; WL = list(ROWS)
R = {(T, r['date']): r for T in WL for r in ROWS[T]}
FIRST = '2026-07-22'
THRESH = {}
# scan-date-only fields (9/25 onward): block participation from the briefs, ask-side call flow-IV from history/flow_iv
import os
WS = '/Users/yuwang/.openclaw/workspace-claw-short'
for D in sorted(os.listdir(f'{WS}/analysis_data')):
    if len(D) != 10 or not D.startswith('2026-') or D < '2026-09-25': continue
    for T in WL:
        f = f'{WS}/analysis_data/{D}/{T}.json'
        if not os.path.exists(f) or (T, D) not in R: continue
        bp = ((json.load(open(f)).get('derived') or {}).get('block_participation') or {}).get('either') or {}
        R[(T, D)]['block_pct'] = bp.get('pct_total')
for T in WL:
    f = f'{WS}/uw_short_fetch/history/flow_iv/{T}.json'
    if not os.path.exists(f): continue
    for D, x in json.load(open(f)).items():
        if (T, D) in R and isinstance(x, dict):
            R[(T, D)]['fiv_call_ask'] = (x.get('call_ask') or {}).get('iv'); R[(T, D)]['fiv_call_all'] = (x.get('call_all') or {}).get('iv')

def row(T, d, k=0):
    i = IDX.get(d)
    if i is None or not (0 <= i + k < len(DAYS)): return None
    return R.get((T, DAYS[i + k]))
def close(T, d, k=0):
    r = row(T, d, k); return r and r['close']
def ret(T, d, k):           # past k-session return
    a, b = close(T, d, -k), close(T, d)
    return b / a - 1 if a and b else None
def fwd(T, d, k):
    a, b = close(T, d), close(T, d, k)
    return b / a - 1 if a and b else None
AVG = {}
for d in DAYS:
    for k in (1, 3, 5):
        v = [x for x in (fwd(T, d, k) for T in WL) if x is not None]
        AVG[(d, k)] = sum(v) / len(v) if len(v) >= 15 else None
def chg(T, d, key, k):
    a, b = row(T, d, -k), row(T, d)
    return (b[key] - a[key]) if a and b and a.get(key) is not None and b.get(key) is not None else None
def g(r, k): return r.get(k)

def stats(events, direction, k):
    v = []
    for T, d in events:
        f = fwd(T, d, k); a = AVG.get((d, k))
        if f is None or a is None: continue
        v.append((d, T, f, f - a))
    if not v: return None
    if direction == 'bear': hit = sum(1 for x in v if x[3] < 0) / len(v); ab = sum(1 for x in v if x[2] < 0) / len(v)
    else: hit = sum(1 for x in v if x[3] > 0) / len(v); ab = sum(1 for x in v if x[2] > 0) / len(v)
    byd = collections.defaultdict(list)
    for x in v: byd[x[0]].append(x[3])
    dm = [sum(y) / len(y) for y in byd.values()]
    td = (st.mean(dm) / (st.pstdev(dm) / math.sqrt(len(dm)))) if len(dm) > 2 and st.pstdev(dm) > 0 else float('nan')
    if direction == 'bear': td = -td
    return {'n': len(v), 'nd': len(byd), 'nt': len({x[1] for x in v}), 'hit': hit, 'abs': ab,
            'exc': st.mean(x[3] for x in v), 'raw': st.mean(x[2] for x in v), 'td': td}

RULES = []
def rule(sec, name, direction, note=''):
    def deco(fn):
        RULES.append((sec, name, direction, note, fn)); return fn
    return deco

def events(fn):
    out = []
    for T in WL:
        for r in ROWS[T]:
            if r['date'] < FIRST: continue
            try:
                if fn(T, r['date'], r): out.append((T, r['date']))
            except (TypeError, ZeroDivisionError, KeyError):
                pass
    return out

# ---------- helpers ----------
def heavy(r, x=1.0): return r.get('dark1D') and r.get('dark_avg1M') and r['dark1D'] >= x * r['dark_avg1M']
def step_up(r): return r['c1M'] < r['c1W'] < r['c2D']
def step_down(r): return r['c1M'] > r['c1W'] > r['c2D']
def doi(T, d, side, k=1): return chg(T, d, f'{side}_open_interest', k)
def iv_up(T, d, k=5): x = chg(T, d, 'iv30', k); return x is not None and x > 0
def iv_dn(T, d, k=5): x = chg(T, d, 'iv30', k); return x is not None and x <= 0
def call_ask_dom(r): return r['call_volume_ask_side'] > r['call_volume_bid_side']
def call_bid_dom(r, x=1.0): return r['call_volume_bid_side'] > x * r['call_volume_ask_side']
def near(a, b, p): return a and b and abs(a - b) / b <= p
def neg_count(d): return sum(1 for T in WL if (R.get((T, d)) or {}).get('net_gamma') is not None and R[(T, d)]['net_gamma'] < 0)
def bear_read(T, d, r):     # the rulebook's distribution read used as the "short signal" for gate tests
    return step_down(r) and r['close'] < r['c2D']
def squeeze_family(r): return (r.get('si_float') or 0) >= 0.10 or (r.get('svr') or 0) >= 0.55
def svr_consec(T, d, x=0.55):
    p = row(T, d, -1); r = row(T, d)
    return r and p and (r.get('svr') or 0) >= x and (p.get('svr') or 0) >= x
def month_end(d):
    i = IDX[d]; nx = DAYS[i + 1] if i + 1 < len(DAYS) else None
    return nx is None or nx[5:7] != d[5:7] or (i + 2 < len(DAYS) and DAYS[i + 2][5:7] != d[5:7])
def ema(vals, n):
    k = 2 / (n + 1); e = None; out = []
    for v in vals:
        e = v if e is None else e + k * (v - e); out.append(e)
    return out

# =============== Part 5 ① magnitude gate ===============
@rule('①量级闸', 'DP 放量本身不给方向（1D dark ≥1.5× 1M 日均）', 'none')
def _(T, d, r): return heavy(r, 1.5)
@rule('①量级闸', '派发读数（1M>1W>2D 且收盘<2D）· 放量时', 'bear', '量级=信心：放量应更准')
def _(T, d, r): return bear_read(T, d, r) and heavy(r, 1.0)
@rule('①量级闸', '派发读数 · 缩量时', 'bear')
def _(T, d, r): return bear_read(T, d, r) and not heavy(r, 1.0)
@rule('①量级闸', '派发读数 · 大单参与度 ≥16%（机构，信任）', 'bear', '只有扫描日（9/25 起）有这个数')
def _(T, d, r): return bear_read(T, d, r) and (r.get('block_pct') or 0) >= 0.16
@rule('①量级闸', '派发读数 · 大单参与度 ≤4%（噪音，降权）', 'bear')
def _(T, d, r): return bear_read(T, d, r) and r.get('block_pct') is not None and r['block_pct'] <= 0.04
@rule('③动机', 'ask 侧 call 的 flow-IV 比前一天高 + 净 call 权利金 >0 = 付溢价抢（有信念）', 'bull', '只有扫描日有 flow-IV')
def _(T, d, r):
    p = row(T, d, -1)
    return r.get('fiv_call_ask') and p and p.get('fiv_call_ask') and r['fiv_call_ask'] > p['fiv_call_ask'] and r['net_call_premium'] > 0
@rule('③动机', 'ask 侧 call 的 flow-IV 平或降 = 没人加注（机械流）', 'none')
def _(T, d, r):
    p = row(T, d, -1)
    return r.get('fiv_call_ask') and p and p.get('fiv_call_ask') and r['fiv_call_ask'] <= p['fiv_call_ask']
# =============== Part 5 ② direction ===============
@rule('②方向', '重心逐级上移 1M<1W<2D 且收盘站在 2D 上（吸筹）', 'bull')
def _(T, d, r): return step_up(r) and r['close'] >= r['c2D']
@rule('②方向', '重心逐级下移 1M>1W>2D（派发）', 'bear')
def _(T, d, r): return step_down(r)
@rule('②方向', '跌后在更低处重建：逐级下移 且 10 日跌', 'bear')
def _(T, d, r): return step_down(r) and ret(T, d, 10) < 0
@rule('②方向', '涨一段后重心停滞（三窗相差 ≤1%，21 日涨 ≥10%）', 'bear', '"停滞本身就是派发信号"')
def _(T, d, r): return abs(r['c2D'] / r['c1M'] - 1) <= 0.01 and abs(r['c1W'] / r['c1M'] - 1) <= 0.01 and ret(T, d, 21) >= 0.10
@rule('②方向', '单看收盘在 2D 重心下方（"单窗偏移不是方向"）', 'none')
def _(T, d, r): return r['close'] < r['c2D']
@rule('②方向', '单看收盘在 2D 重心上方', 'none')
def _(T, d, r): return r['close'] >= r['c2D']
# =============== canonical: multi-window price at DP (today/3d/1w/1m) ===============
@rule('多窗口', '四窗全部上移 1D>3D>1W>1M', 'bull')
def _(T, d, r): return r['c1D'] > r['c3D'] > r['c1W'] > r['c1M']
@rule('多窗口', '四窗全部下移 1D<3D<1W<1M', 'bear')
def _(T, d, r): return r['c1D'] < r['c3D'] < r['c1W'] < r['c1M']
@rule('多窗口', '只有当日冒尖、其它窗口不动（rebalance / noise）', 'none')
def _(T, d, r): return abs(r['c1D'] / r['c3D'] - 1) > 0.03 and abs(r['c3D'] / r['c1W'] - 1) <= 0.01 and abs(r['c1W'] / r['c1M'] - 1) <= 0.02
# =============== Part 6 six fingerprints ===============
@rule('⑤指纹', '吸货：上移 + 站上 2D + call OI 增 + IV30 低位上抬', 'bull')
def _(T, d, r): return step_up(r) and r['close'] >= r['c2D'] and doi(T, d, 'call', 3) > 0 and iv_up(T, d) and (r.get('iv_rank') or 1) <= 0.5
@rule('⑤指纹', '派发：放量 + 重心不上移 + 价格滞涨 + call OI 平降或 put OI 增 + IV 平压', 'bear')
def _(T, d, r): return (heavy(r) and r['c2D'] <= r['c1W'] and ret(T, d, 5) <= 0.01 and (doi(T, d, 'call', 3) <= 0 or doi(T, d, 'put', 3) > 0) and iv_dn(T, d))
@rule('⑤指纹', '库存转移：放量 1.5× + call OI 增 + IV 升 + call 成交 ≥1.5× 30 日均', 'bull', '中性偏多：不该跌')
def _(T, d, r): return heavy(r, 1.5) and doi(T, d, 'call', 1) > 0 and iv_up(T, d, 1) and r['call_volume'] >= 1.5 * r['avg_30_day_call_volume']
@rule('⑤指纹', 'Gamma hedge：贴 flip / call wall 2% 内 + 放量 + 重心不迁移', 'none')
def _(T, d, r): return heavy(r, 1.5) and (near(r['close'], r['flip'], 0.02) or near(r['close'], r['call_wall'], 0.02)) and abs(r['c2D'] / r['c1W'] - 1) <= 0.01
@rule('⑤指纹', '护盘：放量 + put OI 增 + IV 升 + 价格没破 1W 重心', 'none', '降权方向')
def _(T, d, r): return heavy(r) and doi(T, d, 'put', 1) > 0 and iv_up(T, d, 1) and r['close'] >= r['c1W']
def basket_heavy(d): return sum(1 for X in WL if R.get((X, d)) and heavy(R[(X, d)], 1.5)) >= 3
@rule('⑤指纹', 'Fund rebalance：月末放量 1.5× + 同日 ≥3 只一起放量 + call OI 基本不变，当天涨 → 回落', 'bear', '机械流，价格回归')
def _(T, d, r): return month_end(d) and heavy(r, 1.5) and basket_heavy(d) and abs(doi(T, d, 'call', 1)) <= 0.02 * r['call_open_interest'] and ret(T, d, 1) > 0
@rule('⑤指纹', 'Fund rebalance：同上，当天跌 → 回升', 'bull')
def _(T, d, r): return month_end(d) and heavy(r, 1.5) and basket_heavy(d) and abs(doi(T, d, 'call', 1)) <= 0.02 * r['call_open_interest'] and ret(T, d, 1) <= 0
# =============== Part 7 squeeze veto / breaker / gates ===============
@rule('⑦🧨', 'Part 7 宽版：SI ≥10%', 'bull', '禁止做空 = 应该涨')
def _(T, d, r): return (r.get('si_float') or 0) >= 0.10
@rule('⑦🧨', 'Part 7 宽版：借券紧（费率 ≥1%）', 'bull')
def _(T, d, r): return (r.get('fee') or 0) >= 1.0
def borrow_tight(T, d, r):
    past = [row(T, d, -k) for k in range(1, 21)]
    fees = sorted(p['fee'] for p in past if p and p.get('fee') is not None); av = [p['avail'] for p in past if p and p.get('avail')]
    return r.get('fee') and fees and av and r.get('avail') is not None and (r['fee'] >= 2 * fees[len(fees) // 2] or r['avail'] <= 0.5 * max(av))
@rule('⑦🧨', 'Part 7 宽版：借券变紧（费率翻倍或可借量减半，对比 20 日）', 'bull')
def _(T, d, r): return borrow_tight(T, d, r)
@rule('⑦🧨', 'Part 7 宽版：刚急涨（5 日 ≥15%）', 'bull')
def _(T, d, r): return ret(T, d, 5) >= 0.15
@rule('⑦🧨', '原文 🧨（无 vit）：SI≥10% 或 SVR 连日≥55% + DTC≤2 + |收盘−flip|≤3%', 'bull')
def _(T, d, r): return ((r.get('si_float') or 0) >= 0.10 or svr_consec(T, d)) and (r.get('dtc') or 99) <= 2 and near(r['close'], r['flip'], 0.03)
@rule('⑦🧨', '🧨 + 收盘跌破 2D 重心（v3 规则 1 的来源）', 'bear')
def _(T, d, r): return ((r.get('si_float') or 0) >= 0.10 or svr_consec(T, d)) and (r.get('dtc') or 99) <= 2 and near(r['close'], r['flip'], 0.03) and r['close'] < r['c2D']
@rule('⑦🧨', '相位闸：挤仓族 SVR 单日降 ≥10pt（回补尾段）', 'bear', '"偏晚、禁追高" = 不该再涨')
def _(T, d, r): return squeeze_family(row(T, d, -1)) and chg(T, d, 'svr', 1) <= -0.10
@rule('⑦🧨', 'lottery：挤仓族收盘重新站上 flip', 'bull')
def _(T, d, r):
    p = row(T, d, -1)
    return squeeze_family(r) and p['close'] < p['flip'] and r['close'] >= r['flip']
@rule('⑦熔断', '熔断日（全名单负 gamma ≤4/23）的派发读数', 'bear', '熔断 = 这天的空头会失败')
def _(T, d, r): return neg_count(d) <= 4 and bear_read(T, d, r)
@rule('⑦熔断', '非熔断日的派发读数', 'bear')
def _(T, d, r): return neg_count(d) > 4 and bear_read(T, d, r)
@rule('⑦反噬闸', 'SVR ≥50% 名字的派发读数（要挂"挤压反噬"）', 'bear')
def _(T, d, r): return (r.get('svr') or 0) >= 0.50 and bear_read(T, d, r)
@rule('⑦反噬闸', 'SVR <50% 名字的派发读数', 'bear')
def _(T, d, r): return (r.get('svr') or 1) < 0.50 and bear_read(T, d, r)
def group_rally(T, d):
    grp = [X for X in WL if ROWS[X][0].get('group') == ROWS[T][0].get('group')]
    up = [ret(X, d, 1) for X in grp if ret(X, d, 1) is not None]
    return len(up) >= 3 and sum(1 for x in up if x >= 0.02) / len(up) >= 0.6
@rule('⑦反噬闸', '板块轧空日（同组 ≥60% 涨 ≥2%）的派发读数 = 应 veto', 'bear')
def _(T, d, r): return group_rally(T, d) and bear_read(T, d, r)
@rule('⑦财报', '财报前 7 天内的派发读数（应弃权）', 'bear')
def _(T, d, r): return r.get('next_earn') and 0 <= (dt.date.fromisoformat(r['next_earn']) - dt.date.fromisoformat(d)).days <= 7 and bear_read(T, d, r)
@rule('⑦财报', '财报 7 天外的派发读数', 'bear')
def _(T, d, r): return not (r.get('next_earn') and 0 <= (dt.date.fromisoformat(r['next_earn']) - dt.date.fromisoformat(d)).days <= 7) and bear_read(T, d, r)
def pre_earn(r, d): return r.get('next_earn') and 0 <= (dt.date.fromisoformat(r['next_earn']) - dt.date.fromisoformat(d)).days <= 7
@rule('⑦财报', '财报前 7 天内、收盘跌破 2D 重心', 'bear')
def _(T, d, r): return pre_earn(r, d) and r['close'] < r['c2D']
@rule('⑦财报', '财报 7 天外、收盘跌破 2D 重心', 'bear')
def _(T, d, r): return not pre_earn(r, d) and r['close'] < r['c2D']
@rule('空头书', 'put 爆量（≥2× 30 日均）+ 3 日跌 ≥10% = 投降 / 逼空燃料', 'bull')
def _(T, d, r): return r['put_volume'] >= 2 * r['avg_30_day_put_volume'] and ret(T, d, 3) <= -0.10
@rule('结构', 'Contest 日：call、put 成交都 ≥2× 30 日均', 'none', '"等次日分胜负"')
def _(T, d, r): return r['call_volume'] >= 2 * r['avg_30_day_call_volume'] and r['put_volume'] >= 2 * r['avg_30_day_put_volume']
# =============== Part VIII long-side cases ===============
@rule('多头案例', 'AAOI 型：收盘在 flip 下 + call 被写（bid>ask）+ RV>IV', 'bear')
def _(T, d, r): return r['close'] < r['flip'] and call_bid_dom(r) and r['rv21'] > r['iv30']
@rule('多头案例', 'AMKR 型安静吸筹：重心上移 + call ask>bid + 收盘在 flip 上、call wall 下', 'bull')
def _(T, d, r): return r['c2D'] >= r['c1W'] >= r['c1M'] and call_ask_dom(r) and r['flip'] < r['close'] < r['call_wall']
@rule('多头案例', 'WDC 型方向反证：call 以 bid 为主（被写）', 'bear', '不能当多头 = 不该跑赢')
def _(T, d, r): return call_bid_dom(r, 1.2)
@rule('多头案例', '喊多的三条腿（缺 cross）：call ask 买 + IV 上抬 + 收盘在 flip 上', 'bull')
def _(T, d, r): return call_ask_dom(r) and iv_up(T, d, 3) and r['close'] > r['flip']
# =============== TA anchor: 4H EMA 60/200 (RTH 4H bars from UW ohlc/4h, market_time 'r') ===============
TA = {}
for T in WL:
    try:
        b = json.load(open(f'/private/tmp/bt_all/raw/{T}/ohlc4h.json'))['body']
    except OSError:
        continue
    slots = {}
    for x in sorted((b.get('data') if isinstance(b, dict) else b), key=lambda x: (x['start_time'], x.get('market_time') != 'pr')):
        m = slots.get(x['start_time'])
        if m is None: slots[x['start_time']] = dict(x)
        else: m['high'] = max(float(m['high']), float(x['high'])); m['low'] = min(float(m['low']), float(x['low'])); m['close'] = x['close']
    bars = [slots[k] for k in sorted(slots)]
    cl = [float(x['close']) for x in bars]
    e60, e200 = ema(cl, 60), ema(cl, 200)
    import zoneinfo
    for x, a, z in zip(bars, e60, e200):
        dd = dt.datetime.fromisoformat(x['start_time'].replace('Z', '+00:00')).astimezone(zoneinfo.ZoneInfo('America/New_York')).date().isoformat()
        t = TA.setdefault((T, dd), {'lo_touch': False, 'hi_touch': False})
        t['e60'], t['e200'] = a, z          # last bar of the day wins
        if float(x['low']) <= z * 1.005: t['lo_touch'] = True
        if float(x['high']) >= z * 0.995: t['hi_touch'] = True
def strong(T, d):   # uptrend intact: prior day close > EMA60 > EMA200 and the latest 20-day low above the 20 days before
    p = row(T, d, -1); t = TA.get((T, p['date'])) if p else None
    if not t: return False
    lows = [row(T, d, -k)['low'] for k in range(1, 41) if row(T, d, -k)]
    return p['close'] > t['e60'] > t['e200'] and len(lows) == 40 and min(lows[:20]) > min(lows[20:])
@rule('TA', '强势股回踩 4H EMA200 守住 → 大概率反弹', 'bull')
def _(T, d, r):
    t = TA.get((T, d)); return t and strong(T, d) and t['lo_touch'] and r['close'] >= t['e200']
@rule('TA', '黄金窗口：上一条 + EMA200 与 gamma flip 相差 ≤0.5%', 'bull')
def _(T, d, r):
    t = TA.get((T, d)); return t and strong(T, d) and t['lo_touch'] and r['close'] >= t['e200'] and near(t['e200'], r['flip'], 0.005)
@rule('TA', '下跌结构里从下方碰 EMA200 = 阻力，踩了不弹', 'bear')
def _(T, d, r):
    t = TA.get((T, d)); return t and t['e60'] < t['e200'] and t['hi_touch'] and r['close'] < t['e200']
@rule('TA', '失效：强势股 4H 收盘跌破 EMA200', 'bear')
def _(T, d, r):
    t = TA.get((T, d)); return t and strong(T, d) and r['close'] < t['e200']
# =============== IV x RV x price ===============
def ivr(r): return r.get('iv_rank')
@rule('IV×RV', 'IV 低位上抬 + RV>IV 但 RV 回落 = call 行情', 'bull')
def _(T, d, r): return ivr(r) <= 0.3 and iv_up(T, d) and r['rv21'] > r['iv30'] and chg(T, d, 'rv21', 5) < 0
@rule('IV×RV', 'RV>IV 且 IV 高位上行 = 空头行情', 'bear')
def _(T, d, r): return r['rv21'] > r['iv30'] and ivr(r) >= 0.5 and iv_up(T, d)
@rule('IV×RV', 'RV 和价格一起涨 + IV 高位上行 = 空头行情', 'bear')
def _(T, d, r): return chg(T, d, 'rv21', 5) > 0 and ret(T, d, 5) > 0 and ivr(r) >= 0.5 and iv_up(T, d)
@rule('IV×RV', 'IV>RV 且 IV 高位 = 别按趋势读（不空）', 'bull')
def _(T, d, r): return r['iv30'] > r['rv21'] and ivr(r) >= 0.5
@rule('IV×RV', '空头行情（10 日跌 ≥5%）后 IV 翻上 RV = bounce 相位', 'bull')
def _(T, d, r):
    p = row(T, d, -1)
    return p['iv30'] <= p['rv21'] and r['iv30'] > r['rv21'] and ret(T, d, 10) <= -0.05
@rule('IV×RV', 'RV>IV 但 IV 低位 = 多头行情', 'bull')
def _(T, d, r): return r['rv21'] > r['iv30'] and ivr(r) < 0.3
@rule('IV×RV', 'IV>RV 期间两线再交叉 = 价格回归（前 10 日涨→跌）', 'bear')
def _(T, d, r):
    p = row(T, d, -1)
    return p['iv30'] > p['rv21'] and r['iv30'] <= r['rv21'] and ret(T, d, 10) > 0
@rule('IV×RV', 'IV>RV 期间两线再交叉 = 价格回归（前 10 日跌→涨）', 'bull')
def _(T, d, r):
    p = row(T, d, -1)
    return p['iv30'] > p['rv21'] and r['iv30'] <= r['rv21'] and ret(T, d, 10) <= 0
@rule('IV×RV', '顶部机制：涨 ≥15% 后 IV 高位（rank≥0.6）拐头向下 + RV 拐头向上', 'bear')
def _(T, d, r): return ret(T, d, 21) >= 0.15 and ivr(r) >= 0.6 and chg(T, d, 'iv30', 3) < 0 and chg(T, d, 'rv21', 3) > 0
@rule('纪律', '个股 RV 反超 IV = 只管理不开新仓（多头）', 'bear', '不该跑赢')
def _(T, d, r): return r['rv21'] > r['iv30']
# =============== market ===============
@rule('大盘', 'SPY 负 gamma（短 gamma）日的派发读数 = 破位放大', 'bear')
def _(T, d, r): return F['spy_gamma'].get(d, 0) < 0 and bear_read(T, d, r)
@rule('大盘', '红灯日不追超跌反弹：SPY 负 gamma + 5 日跌 ≥10%', 'bear', '反弹会失败')
def _(T, d, r): return F['spy_gamma'].get(d, 0) < 0 and ret(T, d, 5) <= -0.10
@rule('大盘', '对照：非红灯日 5 日跌 ≥10%', 'bull')
def _(T, d, r): return F['spy_gamma'].get(d, 0) >= 0 and ret(T, d, 5) <= -0.10
# =============== UW 双书 / flow discipline ===============
@rule('双书', 'DP 大量在低位（1M 暗池 ≥60% 在收盘下方 + 放量）+ call ask 买 = ⭐双源', 'bull')
def _(T, d, r): return (r.get('dark1M_below_close_share') or 0) >= 0.6 and heavy(r) and call_ask_dom(r)
@rule('双书', 'flow 单独偏多（净 call 权利金>0 且净 put<0）', 'none', 'flow 永不单独定方向')
def _(T, d, r): return r['net_call_premium'] > 0 and r['net_put_premium'] < 0
@rule('双书', 'flow 单独偏空（净 call<0 且净 put>0）', 'none')
def _(T, d, r): return r['net_call_premium'] < 0 and r['net_put_premium'] > 0
@rule('双书', '派发读数 + flow 同向偏空（加一格信心）', 'bear')
def _(T, d, r): return bear_read(T, d, r) and (r['net_call_premium'] < 0 or r['net_put_premium'] > 0)
@rule('双书', '派发读数 + flow 反向偏多（conflict，不下注）', 'bear')
def _(T, d, r): return bear_read(T, d, r) and r['net_call_premium'] > 0 and r['net_put_premium'] <= 0
@rule('双书', '"calls > puts 是陷阱"：call 成交多于 put', 'none')
def _(T, d, r): return r['call_volume'] > 1.5 * r['put_volume']
@rule('双书', 'call 大额在 bid = 写 call = 盖子（bid ≥1.5× ask）', 'bear')
def _(T, d, r): return call_bid_dom(r, 1.5)
# =============== DP 灰色重心迁移法 ===============
@rule('DP迁移法', '吸筹确认：1M<1W<2D + 价格接受新高位（收盘 ≥2D）', 'bull', '不是做空候选')
def _(T, d, r): return step_up(r) and r['close'] >= r['c2D']
@rule('DP迁移法', '派发确认：1M>1W>2D + 高位失守（收盘 <2D）', 'bear')
def _(T, d, r): return bear_read(T, d, r)
@rule('DP迁移法', '派发确认 + GEX/DEX 同向恶化（5 日 net gamma、net delta 都降）', 'bear')
def _(T, d, r): return bear_read(T, d, r) and chg(T, d, 'net_gamma', 5) < 0 and chg(T, d, 'net_delta', 5) < 0
@rule('Call Holder Trap', '近似版 Day 2：Day 1 call、put OI 同时增 + 价格跑在 DP 前面 ≥2%；2 天内收盘跌回旧 core 下 + net gamma 比 Day 1 低', 'bear', '原文第一触发要 cliff 双侧扩张，这里用 OI 代替')
def _(T, d, r):
    for k in (1, 2):
        p = row(T, d, -k)
        if not p or not p.get('c2D') or not p.get('c1W'): continue
        if doi(T, p['date'], 'call', 1) > 0 and doi(T, p['date'], 'put', 1) > 0 and p['close'] >= 1.02 * max(p['c2D'], p['c1W']):
            mid_ok = all(row(T, d, -j)['close'] >= min(p['c2D'], p['c1W']) for j in range(1, k))
            if mid_ok and r['close'] < min(p['c2D'], p['c1W']) and r['net_gamma'] < p['net_gamma']: return True
    return False
# =============== Dealer hedging guide (decision table, call side) ===============
@rule('Dealer表', 'A：call wall 上移 + ask 主导 + call OI 增 → dealer 买股票', 'bull')
def _(T, d, r): return chg(T, d, 'call_wall', 1) > 0 and call_ask_dom(r) and doi(T, d, 'call', 1) > 0
@rule('Dealer表', 'B：call wall 上移 + bid 主导 + call OI 增 → dealer 卖股票', 'bear')
def _(T, d, r): return chg(T, d, 'call_wall', 1) > 0 and call_bid_dom(r) and doi(T, d, 'call', 1) > 0
@rule('Dealer表', 'C：call wall 下移 + bid 主导 + call OI 减 → dealer 卖股票', 'bear')
def _(T, d, r): return chg(T, d, 'call_wall', 1) < 0 and call_bid_dom(r) and doi(T, d, 'call', 1) < 0
@rule('Dealer表', 'D：call wall 下移 + ask 主导 + call OI 减 → dealer 买股票', 'bull')
def _(T, d, r): return chg(T, d, 'call_wall', 1) < 0 and call_ask_dom(r) and doi(T, d, 'call', 1) < 0

def fmt(s):
    if not s: return '   -   '
    return f"{s['hit']*100:3.0f}%/{s['abs']*100:3.0f}% {s['exc']*100:+5.1f}% n{s['n']:4d}({s['nd']:2d}d,{s['nt']:2d}T) td{s['td']:+4.1f}"
def verdict(x):
    s3, s5 = x['s3'], x['s5']
    if not s3 or s3['n'] < 15: return '样本不够'
    h3 = s3['hit']; h5 = s5['hit'] if s5 and s5['n'] >= 10 else None
    tds = [t for t in (s3['td'], s5['td'] if s5 and s5['n'] >= 10 else None) if t is not None and t == t]
    hs = [h for h in (h3, h5) if h is not None]
    if x['dir'] == 'none':
        ok = all(0.42 <= h <= 0.58 for h in hs) and all(abs(t) < 2 for t in tds)
        return '成立（没方向）' if ok else ('不成立：偏涨' if st.mean(hs) > 0.5 else '不成立：偏跌')
    if max(hs) >= 0.60 and min(hs) >= 0.55 and (not tds or max(tds) >= 1.5): return '成立'
    if max(hs) <= 0.45 and (min(hs) <= 0.42 or (tds and min(tds) <= -1.5)): return '反向'
    return '没优势'

if __name__ == '__main__':
    out = []
    for sec, name, direction, note, fn in RULES:
        ev = events(fn)
        s = {k: stats(ev, direction, k) for k in (1, 3, 5)}
        out.append({'sec': sec, 'name': name, 'dir': direction, 'note': note, 'n_events': len(ev),
                    **{f's{k}': s[k] for k in (1, 3, 5)}})
        out[-1]['verdict'] = verdict(out[-1])
        print(f"[{sec}] {name} ({direction}{' · ' + note if note else ''}) => {out[-1]['verdict']}\n      1D {fmt(s[1])} | 3D {fmt(s[3])} | 5D {fmt(s[5])}")
    json.dump(out, open('/private/tmp/bt_all/rules_out.json', 'w'), ensure_ascii=False, indent=0)
