"""ZZ 2026-11-16 "只回测dp重心有关的规则": every DP-centroid rule from Olivia's 灰色重心迁移法, the DP parts of SHORT_ENGINE v3,
RULEBOOK.pdf's DP direction/fingerprint lines and the 11/12 additions, each tested ALONE (no options / SI / gamma / IV legs).
Sample 2025-12-11 -> 2026-11-13, 23 names (panel5.json). Outcome = close-to-close 3/5/10D return vs the 23-name equal-weight
average of the same dates (as in every earlier backtest); 'fell' = raw return < 0; beta-adjusted = return - beta * average with
an ex-ante 60-session beta. Thresholds marked (mine) are not in the source docs."""
import json, math, statistics as st, collections, sys
P = json.load(open('/Users/yuwang/.openclaw/workspace-claw-short/analysis_data/backtest-2026-10-18/dp_centroid/panel5.json'))
days, panel = P['days'], P['panel']
WL = list(panel)
IDX = {d: i for i, d in enumerate(days)}
ROW = {(T, r['date']): r for T in WL for r in panel[T]}
FIRST = '2025-12-11'
H = (3, 5, 10)
OPT = {'LITE', 'COHR', 'AAOI', 'GLW', 'AEHR'}
QS = (('2025-12-11', '2026-02-28', '12–2月'), ('2026-03-01', '2026-05-31', '3–5月'),
      ('2026-06-01', '2026-08-31', '6–8月'), ('2026-09-01', '2026-11-13', '9–11月'))

def R(T, i): return ROW.get((T, days[i])) if 0 <= i < len(days) else None
def close(T, i): r = R(T, i); return r['close'] if r else None
def ret(T, i, k):   # trailing k-session return up to day i
    a, b = close(T, i - k), close(T, i); return b / a - 1 if a and b else None
def fwd(T, i, k): a, b = close(T, i), close(T, i + k); return b / a - 1 if a and b else None
AVG = {}
for i in range(len(days)):
    for k in (1,) + H:
        v = [x for x in (fwd(T, i, k) for T in WL) if x is not None]
        AVG[(i, k)] = sum(v) / len(v) if len(v) >= 20 else None
# ex-ante beta vs the equal-weight average, last 60 sessions (min 20)
BETA = {}
for T in WL:
    for i in range(len(days)):
        xs, ys = [], []
        for j in range(max(1, i - 60), i):
            y, x = fwd(T, j - 1, 1), AVG.get((j - 1, 1))
            if y is not None and x is not None: xs.append(x); ys.append(y)
        if len(xs) >= 20:
            mx, my = st.mean(xs), st.mean(ys); vx = sum((x - mx) ** 2 for x in xs)
            BETA[(T, i)] = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / vx if vx else 1.0
def ev(T, i):
    e = {'T': T, 'i': i, 'date': days[i]}
    for k in H:
        f, a = fwd(T, i, k), AVG.get((i, k))
        e[f'r{k}'] = f
        e[f'x{k}'] = f - a if f is not None and a is not None else None
        b = BETA.get((T, i), 1.0)
        e[f'b{k}'] = f - b * a if f is not None and a is not None else None
    return e

# ---------- helpers ----------
def ok(r, *ks): return r is not None and all(r.get(k) is not None for k in ks)
def step_down(r): return r['c1M'] > r['c1W'] > r['c2D']
def step_up(r): return r['c1M'] < r['c1W'] < r['c2D']
def below2D(r): return r['close'] < r['c2D']
def heavy(r, x=1.3): return r.get('avg1M') and r['dark'] >= x * r['avg1M']
def moveup(T, i):
    r, pc = R(T, i), close(T, i - 1)
    return pc and (r['high'] / pc - 1) >= (1 - r['low'] / pc)
def first_break(T, i):
    r, p = R(T, i), R(T, i - 1)
    return ok(p, 'c2D') and below2D(r) and p['close'] >= p['c2D']
def run_up_1m(T, i, x=0.10):   # (mine) "一段上涨之后": highest close of the last 21 sessions >= 10% above the close 21 sessions ago
    a = close(T, i - 21)
    hi = max((close(T, j) for j in range(i - 20, i + 1) if close(T, j)), default=None)
    return a and hi and hi / a - 1 >= x

RULES = []
def rule(group, name, direction, note=''):
    def deco(fn): RULES.append((group, name, direction, note, fn)); return fn
    return deco
def events(fn):
    out = []
    for T in WL:
        for i, d in enumerate(days):
            r = R(T, i)
            if d < FIRST or not ok(r, 'c1D', 'c2D', 'c3D', 'c1W', 'c1M') or close(T, i - 1) is None: continue
            try:
                if fn(T, i, r): out.append(ev(T, i))
            except (TypeError, ZeroDivisionError, KeyError):
                pass
    return out

# =============== A. 灰色重心迁移法 (Olivia) ===============
@rule('A 灰色重心迁移法', '派发确认：1M>1W>2D 逐级下移 + 收盘跌回 2D 下方（高位失守）', 'bear')
def _(T, i, r): return step_down(r) and below2D(r)
@rule('A 灰色重心迁移法', '派发确认，且是在一段上涨之后（1 个月内最高收盘比 1 个月前高 ≥10%）', 'bear', '"尤其发生在一段上涨之后"；10% 是我定的')
def _(T, i, r): return step_down(r) and below2D(r) and run_up_1m(T, i)
@rule('A 灰色重心迁移法', '只看逐级下移 1M>1W>2D（不管价格）', 'bear')
def _(T, i, r): return step_down(r)
@rule('A 灰色重心迁移法', '吸筹确认：1M<1W<2D 逐级上移 + 收盘站在 2D 上方（价格接受新高位）', 'bull', '原文：不是做空候选')
def _(T, i, r): return step_up(r) and not below2D(r)
@rule('A 灰色重心迁移法', '只看逐级上移 1M<1W<2D（不管价格）', 'bull')
def _(T, i, r): return step_up(r)
def trap_warn(T, i, r):   # (mine, as in dp_trap) close >= 5% above the lowest of the prior 3 closes and >= 2% above max(2D, 1W)
    prev = [x for x in (close(T, i - 1), close(T, i - 2), close(T, i - 3)) if x]
    return prev and r['close'] / min(prev) - 1 >= 0.05 and r['close'] >= 1.02 * max(r['c2D'], r['c1W'])
@rule('A 灰色重心迁移法', 'Trap warning：价格急涨（比前 3 天最低收盘高 ≥5%）、跑在 2D/1W 重心前面 ≥2%', 'wait', '原文：不是派发确认，等回踩裁决；当空头测')
def _(T, i, r): return trap_warn(T, i, r)
@rule('A 灰色重心迁移法', 'Confirmed trap：Trap warning 之后 3 天内收盘跌穿那天的共同 core（min(2D,1W)）', 'bear', 'COHR 8/17→8/18 案例')
def _(T, i, r):
    for j in range(1, 4):
        p = R(T, i - j)
        if ok(p, 'c2D', 'c1W', 'c1M') and close(T, i - j - 1) and trap_warn(T, i - j, p):
            lo = min(p['c2D'], p['c1W'])
            if r['close'] < lo and all(close(T, m) >= lo for m in range(i - j + 1, i)): return True
    return False
def acceptance_episodes(b=0.03, M=10, tol=0.01):
    """价格裁决 (as dp_trap/accept.py): setup = 2D >= 1W*1.03 and close >= 2D*0.98 (node N = 2D, old core O = 1W, fixed);
    A = touched N within 1% with every close since >= N, then a new closing high; B = first close < O. One episode at a time."""
    A, Bf, Bs = [], [], []
    for T in WL:
        i = 0
        while i < len(days):
            r = R(T, i)
            if days[i] < FIRST or not ok(r, 'c2D', 'c1W') or not (r['c2D'] >= r['c1W'] * (1 + b) and r['close'] >= r['c2D'] * 0.98):
                i += 1; continue
            N, O = r['c2D'], r['c1W']; held, touched, hi, res = True, False, r['close'], None
            for j in range(i + 1, min(i + M, len(days) - 1) + 1):
                rj = R(T, j)
                if not rj: continue
                if rj['close'] < O: res = ('B', j); break
                if rj['close'] < N: held = False
                if held and rj['low'] <= N * (1 + tol): touched = True
                if held and touched and rj['close'] > hi: res = ('A', j); break
                hi = max(hi, rj['close'])
            if res and res[0] == 'A': A.append(ev(T, res[1]))
            elif res: (Bf if res[1] - i <= 3 else Bs).append(ev(T, res[1]))
            i = (res[1] if res else i + M) + 1
    return A, Bf, Bs
ACC_A, ACC_BF, ACC_BS = acceptance_episodes()
@rule('A 灰色重心迁移法', '价格裁决 · 失败：冲进高位 DP 区后 3 天内跌回旧 core（1W）下方', 'bear', '高位区 = 2D 比 1W 高 ≥3%（我定的）')
def _(T, i, r): return ('ACC_BF', T, i)
@rule('A 灰色重心迁移法', '价格裁决 · 失败得慢：4–10 天后才跌回旧 core 下方', 'bear')
def _(T, i, r): return ('ACC_BS', T, i)
@rule('A 灰色重心迁移法', '价格裁决 · 健康 acceptance：回踩新 node 守住、再创新高', 'bull')
def _(T, i, r): return ('ACC_A', T, i)
@rule('A 灰色重心迁移法', 'Step 5 回踩：昨天收在 2D 上方，今天盘中碰到 2D、收盘守住', 'bull', '"第一次重要回踩是否 defend DP core"')
def _(T, i, r):
    p = R(T, i - 1)
    return ok(p, 'c2D') and p['close'] >= p['c2D'] and r['low'] <= r['c2D'] <= r['close']
@rule('A 灰色重心迁移法', 'Step 4 价格跑在库存前面：收盘高出 1W 重心 ≥8%', 'bear', '8% 同 10/30 预警测试（我定的）')
def _(T, i, r): return r['close'] >= 1.08 * r['c1W']

# =============== B. SHORT_ENGINE v3 里只跟重心有关的部分 ===============
@rule('B SHORT_ENGINE v3', '收盘跌破 2D 重心（四条规则的共同前提，单独看）', 'bear')
def _(T, i, r): return below2D(r)
@rule('B SHORT_ENGINE v3', '  第一天跌破 2D', 'bear')
def _(T, i, r): return first_break(T, i)
@rule('B SHORT_ENGINE v3', '  已连续 2 天以上在 2D 下方', 'bear')
def _(T, i, r): return below2D(r) and not first_break(T, i)
@rule('B SHORT_ENGINE v3', '  浅：第一天跌破、不到 2%', 'bear')
def _(T, i, r): return first_break(T, i) and r['c2D'] / r['close'] - 1 <= 0.02
@rule('B SHORT_ENGINE v3', '  深：跌破超过 2%，或不是第一天', 'bear')
def _(T, i, r): return below2D(r) and not (first_break(T, i) and r['c2D'] / r['close'] - 1 <= 0.02)
@rule('B SHORT_ENGINE v3', '站回 2D 重心（"规则失效"）：昨天在 2D 下方，今天收盘站回', 'bull')
def _(T, i, r):
    p = R(T, i - 1); return ok(p, 'c2D') and p['close'] < p['c2D'] and not below2D(r)
@rule('B SHORT_ENGINE v3', '收复 1W 重心（"空头作废"）：昨天在 1W 下方，今天收盘站回', 'bull')
def _(T, i, r):
    p = R(T, i - 1); return ok(p, 'c1W') and p['close'] < p['c1W'] and r['close'] >= r['c1W']

# =============== C. RULEBOOK.pdf (σ) 的 DP 方向 / 指纹 ===============
@rule('C RULEBOOK', '② 吸筹：today/1W/1M 重心上移，收盘站在每一级上方', 'bull')
def _(T, i, r): return r['c1M'] < r['c1W'] < r['c1D'] and r['close'] >= max(r['c1D'], r['c1W'], r['c1M'])
@rule('C RULEBOOK', '② 派发：today/1W/1M 重心下移或走平（1% 内），而且是跌了之后在更低处重建（10 日跌）', 'bear', '1% 是我定的')
def _(T, i, r): return r['c1D'] <= r['c1W'] * 1.01 and r['c1W'] <= r['c1M'] * 1.01 and (ret(T, i, 10) or 0) < 0
@rule('C RULEBOOK', '四窗全部下移 1D<3D<1W<1M（跨窗一致 = 派发）', 'bear')
def _(T, i, r): return r['c1D'] < r['c3D'] < r['c1W'] < r['c1M']
@rule('C RULEBOOK', '四窗全部上移 1D>3D>1W>1M（跨窗一致 = 吸货）', 'bull')
def _(T, i, r): return r['c1D'] > r['c3D'] > r['c1W'] > r['c1M']
@rule('C RULEBOOK', '派发指纹的 DP 部分：放量 + 价位不上迁（2D≤1W）+ 价顶不动（5 日涨 ≤1%）', 'bear', '期权 / IV 那几项不算')
def _(T, i, r): return heavy(r) and r['c2D'] <= r['c1W'] and (ret(T, i, 5) or 0) <= 0.01
@rule('C RULEBOOK', '停滞：涨一段后（21 日涨 ≥10%）三窗重心相差 ≤1%（"停滞本身就是早于下迁的派发信号"）', 'bear')
def _(T, i, r): return abs(r['c2D'] / r['c1M'] - 1) <= 0.01 and abs(r['c1W'] / r['c1M'] - 1) <= 0.01 and (ret(T, i, 21) or 0) >= 0.10
@rule('C RULEBOOK', '头顶供给：1M 暗池量 ≥2/3 在收盘价上方', 'bear', '2/3 是我定的')
def _(T, i, r): return r.get('above1M') is not None and r['above1M'] >= 2 / 3
@rule('C RULEBOOK', '只有当日冒尖、其它窗口不动（rebalance / noise：原文说不读方向）', 'none')
def _(T, i, r): return abs(r['c1D'] / r['c3D'] - 1) > 0.03 and abs(r['c3D'] / r['c1W'] - 1) <= 0.01 and abs(r['c1W'] / r['c1M'] - 1) <= 0.02

# =============== D. 11/12 加的 ===============
@rule('D 11/12 新加', '放量 1.3× + 冲高 + 重心没跟上价格（1D 重心在当天区间下半段）', 'bear', '报告 Dark Pool 段第二行的判断')
def _(T, i, r): return heavy(r) and moveup(T, i) and r.get('pos') is not None and r['pos'] < 0.5
@rule('D 11/12 新加', '  不管放不放量：冲高 + 重心没跟上价格', 'bear')
def _(T, i, r): return moveup(T, i) and r.get('pos') is not None and r['pos'] < 0.5
@rule('D 11/12 新加', 'Olivia 核心做空：放量 1.3× + 收盘在当天最密价带下方 + 在 1M 重心下方', 'bear')
def _(T, i, r): return heavy(r) and r['close'] < r['band_lo'] and r['close'] < r['c1M']
@rule('D 11/12 新加', 'ZZ：放量冲高 + 收盘掉回最密价带下方 + 仍在 1M 重心上方', 'bear')
def _(T, i, r): return heavy(r) and moveup(T, i) and r['close'] < r['band_lo'] and r['close'] >= r['c1M']

# ---------- scoring ----------
BASE = events(lambda T, i, r: True)
def score(E, k, direction, key='x'):
    v = [e for e in E if e.get(f'{key}{k}') is not None]
    if not v: return None
    sgn = -1 if direction in ('bear', 'wait', 'none') else 1
    hit = sum(1 for e in v if e[f'{key}{k}'] * sgn > 0) / len(v)
    fell = sum(1 for e in v if e[f'r{k}'] < 0) / len(v)
    byd = collections.defaultdict(list)
    for e in v: byd[e['date']].append(e[f'{key}{k}'])
    dm = [sum(x) / len(x) for x in byd.values()]
    td = st.mean(dm) / (st.pstdev(dm) / math.sqrt(len(dm))) if len(dm) > 2 and st.pstdev(dm) > 0 else float('nan')
    return {'n': len(v), 'nd': len(byd), 'hit': hit, 'fell': fell, 'mx': st.mean(e[f'{key}{k}'] for e in v),
            'med': st.median(e[f'{key}{k}'] for e in v), 'td': td}
BASEK = {(k, dirn, key): score(BASE, k, dirn, key) for k in H for dirn in ('bear', 'bull') for key in ('x', 'b')}
def dedup(E, gap=5):
    last, out = {}, []
    for e in sorted(E, key=lambda e: (e['T'], e['i'])):
        if e['T'] in last and e['i'] - last[e['T']] <= gap: continue
        last[e['T']] = e['i']; out.append(e)
    return out
def verdict(E, direction):
    """(mine) 5D: right-signed mean excess with |td| >= 2, beta-adjusted mean excess same sign, and the hit rate above the
    base in >= 3 of the 4 quarters that have >= 8 events; '反向' mirrors it. n < 25 -> 样本不够."""
    if direction in ('none',): return None
    s5 = score(E, 5, direction); b5 = score(E, 5, direction, 'b')
    if not s5 or s5['n'] < 25: return '样本不够'
    sgn = -1 if direction in ('bear', 'wait') else 1
    base_hit = BASEK[(5, 'bear' if sgn < 0 else 'bull', 'x')]['hit']
    qs = []
    for lo, hi, _ in QS:
        q = score([e for e in E if lo <= e['date'] <= hi], 5, direction)
        if q and q['n'] >= 8: qs.append(q['hit'] > base_hit)
    good = s5['mx'] * sgn > 0 and abs(s5['td']) >= 2 and b5['mx'] * sgn > 0 and sum(qs) >= 3
    bad = s5['mx'] * sgn < 0 and abs(s5['td']) >= 2 and b5['mx'] * sgn < 0 and sum(not q for q in qs) >= 3
    return '有优势' if good else '反向' if bad else '没优势'
def fmt(s, base):
    if not s: return 'n0'
    return (f"{s['hit']*100:3.0f}%(基准{base['hit']*100:2.0f}) 跌{s['fell']*100:3.0f}% 超额{s['mx']*100:+5.1f}/中位{s['med']*100:+5.1f}pp "
            f"td{s['td']:+.1f} n{s['n']}")
def show(group, name, direction, note, E, out):
    word = {'bear': '跑输', 'wait': '跑输', 'none': '跑输', 'bull': '跑赢'}[direction]
    bd = 'bull' if direction == 'bull' else 'bear'
    v = verdict(E, direction)
    lines = [f"[{group}] {name} ({direction}{' · ' + note if note else ''}) => {v or '（原文说没方向）'}"]
    lines.append(f"    {word} " + ' | '.join(f"{k}D {fmt(score(E, k, direction), BASEK[(k, bd, 'x')])}" for k in H))
    b = score(E, 5, direction, 'b'); bb = BASEK[(5, bd, 'b')]
    lines.append(f"    β调整 5D {fmt(b, bb)} · 同票 5 天只算第一次 5D {fmt(score(dedup(E), 5, direction), BASEK[(5, bd, 'x')])}")
    qs = []
    for lo, hi, lab in QS:
        q = score([e for e in E if lo <= e['date'] <= hi], 5, direction)
        qs.append(f"{lab} {q['hit']*100:.0f}%/{q['mx']*100:+.1f}pp n{q['n']}" if q else f'{lab} n0')
    o = score([e for e in E if e['T'] in OPT], 5, direction); n_ = score([e for e in E if e['T'] not in OPT], 5, direction)
    lines.append('    5D 分季度 ' + ' · '.join(qs) + f" | 光模块 {o['hit']*100:.0f}%/{o['mx']*100:+.1f}pp n{o['n']}" if o else '    5D 分季度 ' + ' · '.join(qs))
    if n_: lines[-1] += f" · 其他 {n_['hit']*100:.0f}%/{n_['mx']*100:+.1f}pp n{n_['n']}"
    print('\n'.join(lines)); out.append({'group': group, 'name': name, 'direction': direction, 'note': note, 'verdict': v,
                                       **{f'{k}D': score(E, k, direction) for k in H}, '5D_beta': b,
                                       'events': [(e['T'], e['date']) for e in E]})

if __name__ == '__main__':
    print(f"样本 {FIRST} → {days[-1]}，23 只，name-days {len(BASE)}（3D 结果到 {days[-4]}，5D 到 {days[-6]}，10D 到 {days[-11]}）")
    for k in H:
        print(f"基准 {k}D: 跑输 {BASEK[(k,'bear','x')]['hit']*100:.0f}% · 跌 {BASEK[(k,'bear','x')]['fell']*100:.0f}% · 超额中位 {BASEK[(k,'bear','x')]['med']*100:+.1f}pp")
    out = []
    special = {'ACC_A': ACC_A, 'ACC_BF': ACC_BF, 'ACC_BS': ACC_BS}
    for group, name, direction, note, fn in RULES:
        probe = None
        try: probe = fn(WL[0], IDX[FIRST], R(WL[0], IDX[FIRST]))
        except Exception: pass
        E = special[probe[0]] if isinstance(probe, tuple) else events(fn)
        show(group, name, direction, note, E, out)
    json.dump(out, open('/Users/yuwang/.openclaw/workspace-claw-short/analysis_data/backtest-2026-10-18/dp_centroid/rules_out.json', 'w'), ensure_ascii=False)
