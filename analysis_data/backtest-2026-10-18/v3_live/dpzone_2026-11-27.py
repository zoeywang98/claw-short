# One-off (ZZ 2026-11-27 13:51 "不是，不只是看空，就看dp 重心，是不是符合放量涨不上去，放量跌不下去"): both directions,
# DP-only, scored by price afterwards (no stops).
# Part 1: every 暗池区间盯 "符合" (daily_short/dpzone/log_<D>.txt, first 符合 of each zone each day, 11/11–11/27):
#   派发 "放量但涨不上去" wins if price is lower later; 吸筹 "放量但跌不下去" wins if price is higher later.
#   Raw from the alert price to that day's close (0D) / 1D / 3D / latest close; vs the 23-name average from that day's close.
#   Control = the same watched zones on days they did not turn 符合 (last status of the day).
# Part 2: the evening brief's day_flow (template_inputs.dark_pool.day_flow, post-close scans 11/12–11/25, all names):
#   放量 (>=1.3x 1M avg) + up move + centroid not following = 涨不上去 (bear); 放量 + down move + not following = 跌不下去 (bull).
# Closes: closes_2026-11-27.json (UW ohlc/1d regular session, incl. V and GOOGL; 11/27 half day).
import json, os, re, statistics as st
WS = '/Users/yuwang/.openclaw/workspace-claw-short'
DZ = f'{WS}/daily_short/dpzone'; LOGS = f'{WS}/daily_short/logs'
HERE = os.path.dirname(os.path.abspath(__file__))
X = json.load(open(f'{HERE}/closes_2026-11-27.json'))
BOARD = sorted(f[:-11] for f in os.listdir(f'{LOGS}/2026-10-16') if f.endswith('.reply.json') and not f.startswith('_'))
days = sorted(set.intersection(*[set(X[T]) for T in BOARD])); days = [d for d in days if d >= '2026-10-01']
idx = {d: i for i, d in enumerate(days)}; last = days[-1]
def at(d, k):
    j = idx[d] + k
    return days[j] if j < len(days) else None
def board(d, e):
    return st.mean(X[U][e] / X[U][d] - 1 for U in BOARD)
ENT = re.compile(r'^(\S+) (\d+)/(\d+)(?: px ([\d.]+) (.+?))?(?: no bars)?$')
ev = []   # one row per zone per day
for f in sorted(os.listdir(DZ)):
    m = re.fullmatch(r'log_(\d{4}-\d{2}-\d{2})\.txt', f)
    if not m or m.group(1) not in idx:
        continue
    D = m.group(1)
    s = json.load(open(f'{DZ}/state_{D}.json'))
    keys = list(s.get('tallies', {}))
    for k in s.get('alerted', []):
        if k not in keys: keys.append(k)
    tick = {}
    for k in keys: tick.setdefault(k.split('|')[0], []).append(k)
    Z = {k: {'first': None, 'lastwhy': None, 'lastpx': None} for k in keys}
    for line in open(f'{DZ}/{f}'):
        line = re.sub(r'(\s*\([^()]*\))+\s*$', '', line.strip())
        mt = re.match(r'^(\d\d:\d\d) (.*)$', line)
        if not mt or mt.group(1) >= '16:00':
            continue
        t, parts = mt.group(1), mt.group(2).split(' · ')
        for i, p in enumerate(parts):
            e = ENT.match(p.strip())
            if not e or e.group(4) is None:
                continue
            T, px, why = e.group(1), float(e.group(4)), e.group(5).strip()
            if len(parts) == len(s.get('tallies', {})) and list(s['tallies'])[i].split('|')[0] == T:
                k = list(s['tallies'])[i]
            elif len(tick.get(T, [])) == 1:
                k = tick[T][0]
            else:
                continue
            z = Z[k]
            if why.startswith('符合') and z['first'] is None:
                z['first'] = (t, px)
            z['lastwhy'], z['lastpx'] = why, px
    for k, z in Z.items():
        T, rng, kind = k.split('|')[:3]
        if T not in X or z['lastwhy'] is None:
            continue
        ok = z['first'] is not None or k in s.get('alerted', [])
        px = z['first'][1] if z['first'] else None
        r = {'D': D, 'T': T, 'zone': rng, 'kind': kind, 'auto': k.endswith('|auto'), 'ok': ok, 'px': px,
             't': z['first'][0] if z['first'] else None, 'lastwhy': re.sub(r' [\d.]+$', '', z['lastwhy'])}
        for h in (1, 3, 5):
            e = at(D, h)
            r[h] = None if e is None else (X[T][e] / X[T][D] - 1, X[T][e] / X[T][D] - 1 - board(D, e))
        r['0'] = X[T][D] / px - 1 if px else None
        r['pxk'] = {h: (X[T][at(D, h)] / px - 1 if px and at(D, h) else None) for h in (1, 3)}
        r['now'] = X[T][last] / px - 1 if px and D < last else None
        ev.append(r)
def sign(kind):
    return -1 if kind == 'dist' else 1      # dist wins when price falls, accum when it rises
def show(lab, E, from_alert=True):
    out = []
    if from_alert:
        for h, get in (('当天收盘', lambda r: r['0']), ('1D', lambda r: r['pxk'][1]), ('3D', lambda r: r['pxk'][3]), ('到' + last[5:], lambda r: r['now'])):
            v = [(get(r), r['kind']) for r in E if get(r) is not None]
            out.append(f"{h} 对 {sum(x * sign(k) > 0 for x, k in v)}/{len(v)} 均 {st.mean(x for x, _ in v) * 100:+.1f}%" if v else f'{h} -')
    for h in (1, 3, 5):
        v = [(r[h], r['kind']) for r in E if r[h] is not None]
        out.append(f"收盘起{h}D 对 {sum(x[0] * sign(k) > 0 for x, k in v)}/{len(v)} 比板块对 {sum(x[1] * sign(k) > 0 for x, k in v)}/{len(v)} 超额 {st.mean(x[1] for x, _ in v) * 100:+.1f}" if v else f'{h}D -')
    print(f'{lab:24s} | ' + ' | '.join(out))
print(f'closes to {last}; board = {len(BOARD)} names; zone-days {len(ev)}\n== Part 1 暗池区间盯（从提醒价起算；"对" = 派发跌了 / 吸筹涨了）')
show('派发 符合（放量涨不上去）', [r for r in ev if r['kind'] == 'dist' and r['ok']])
show('吸筹 符合（放量跌不下去）', [r for r in ev if r['kind'] == 'accum' and r['ok']])
show('  其中 VRT 手设', [r for r in ev if r['kind'] == 'accum' and r['ok'] and not r['auto']])
show('  其中 自动区间', [r for r in ev if r['kind'] == 'accum' and r['ok'] and r['auto']])
print('-- 对照：同样在盯、当天没符合（从当天收盘起）')
for kind, nm in (('dist', '派发'), ('accum', '吸筹')):
    E = [r for r in ev if r['kind'] == kind and not r['ok']]
    for w in sorted({r['lastwhy'] for r in E}):
        show(f'{nm} 没符合·收盘时{w[:8]}', [r for r in E if r['lastwhy'] == w], from_alert=False)
print('-- 逐次（符合）')
for r in sorted((r for r in ev if r['ok']), key=lambda r: (r['D'], r['T'])):
    f = lambda x: '   -  ' if x is None else f'{x * 100:+5.1f}%'
    print(f"  {r['D'][5:]} {r['t'] or '?':5s} {r['T']:5s} {r['zone']:12s} {'派发' if r['kind'] == 'dist' else '吸筹'}{'·自动' if r['auto'] else '·手设'} 提醒价 {r['px'] or 0:8.2f} | 当天收盘 {f(r['0'])} 1D {f(r['pxk'][1])} 3D {f(r['pxk'][3])} 到{last[5:]} {f(r['now'])}"
          + (f" | 板块 1D {board(r['D'], at(r['D'], 1)) * 100:+.1f}%" if at(r['D'], 1) else ''))
# ---- Part 2: day_flow in the evening briefs
SC = sorted(d for d in os.listdir(LOGS) if re.fullmatch(r'\d{4}-\d{2}-\d{2}', d) and d >= '2026-11-12')
rows = []
for d in SC:
    for f in sorted(os.listdir(f'{LOGS}/{d}')):
        if not f.endswith('.reply.json') or f.startswith('_'): continue
        T = f[:-11]; p = f'{WS}/analysis_data/{d}/{T}.json'
        if not os.path.exists(p) or T not in X or d not in idx: continue
        df = ((json.load(open(p)).get('template_inputs') or {}).get('dark_pool') or {}).get('day_flow')
        if not df: continue
        vol = (df.get('vs_1m_avg') or 0) >= 1.3
        cat = '粗' if df.get('coarse') else f"{'放量' if vol else '没放量'}·{'涨' if df['move'] == 'up' else '跌'}·{'跟' if df['followed'] else '没跟'}"
        r = {'D': d, 'T': T, 'cat': cat}
        for h in (1, 3, 5):
            e = at(d, h)
            r[h] = None if e is None else (X[T][e] / X[T][d] - 1, X[T][e] / X[T][d] - 1 - board(d, e))
        rows.append(r)
def show2(lab, E, kind):
    out = []
    for h in (1, 3, 5):
        v = [r[h] for r in E if r[h] is not None]
        out.append(f"{h}D {'跌' if kind == 'dist' else '涨'}了 {sum(x * sign(kind) > 0 for x, _ in v)}/{len(v)} 比板块对 {sum(y * sign(kind) > 0 for _, y in v)}/{len(v)} 超额 {st.mean(y for _, y in v) * 100:+.1f}" if v else f'{h}D -')
    print(f'{lab:26s} | ' + ' | '.join(out))
print(f'\n== Part 2 晚上报告 day_flow（{SC[0][5:]}–{SC[-1][5:]} 收盘扫描，从当天收盘起）')
show2('放量冲高·重心没跟上（涨不上去）', [r for r in rows if r['cat'] == '放量·涨·没跟'], 'dist')
show2('放量下跌·重心没跟下去（跌不下去）', [r for r in rows if r['cat'] == '放量·跌·没跟'], 'accum')
show2('放量冲高·重心跟上', [r for r in rows if r['cat'] == '放量·涨·跟'], 'accum')
show2('放量下跌·重心跟下去', [r for r in rows if r['cat'] == '放量·跌·跟'], 'dist')
show2('没放量 全部（按跌算）', [r for r in rows if r['cat'].startswith('没放量')], 'dist')
show2('全部（按跌算）', rows, 'dist')
from collections import Counter
print('counts:', Counter(r['cat'] for r in rows))
