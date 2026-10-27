"""Win rates for the right card (失败 / trapped inventory): relative (lagged the 23-name average) and absolute (price fell),
plus a held short: enter at the failure close, exit on a close back above the stop or after 10 sessions."""
exec(open('/Users/yuwang/.openclaw/workspace-claw-short/analysis_data/backtest-2026-10-18/dp_trap/accept2.py').read().split("print('A = beat")[0])
idx = {d: i for i, d in enumerate(days)}
def wr(E, k):
    v = [e for e in E if e.get(f'r{k}') is not None and e.get(f'e{k}') is not None]
    if not v: return '-'
    rel = sum(1 for e in v if e[f'e{k}'] < 0) / len(v); ab = sum(1 for e in v if e[f'r{k}'] < 0) / len(v)
    return f"相对 {rel*100:.0f}% 绝对 {ab*100:.0f}% 均值 {st.mean(e[f'r{k}'] for e in v)*100:+.1f}% (n {len(v)})"
def hold(E, stop_kind):
    out = []
    for e in E:
        T, i = e['T'], e['i']; r = R(T, i); entry = r['close']
        stop = e['O'] if stop_kind == 'old core' else r['c2D']
        j_exit = None
        for j in range(i + 1, min(i + 10, len(days) - 1) + 1):
            rj = R(T, j)
            if rj and rj['close'] > stop: j_exit = j; break
        if j_exit is None:
            if i + 10 > len(days) - 1: continue      # not finished yet
            j_exit = i + 10
        out.append(-(R(T, j_exit)['close'] / entry - 1))
    if not out: return '-'
    return f"{len(out)} 笔 赚钱 {sum(1 for x in out if x > 0)/len(out)*100:.0f}% 平均 {st.mean(out)*100:+.1f}% 中位 {st.median(out)*100:+.1f}%"
def runB(b, M):
    Bv = []
    for T in WL:
        i = 0
        while i < len(days):
            r = R(T, i)
            if not (r and r['c2D'] and r['c1W'] and days[i] >= '2026-07-22' and r['c2D'] >= r['c1W'] * (1 + b) and r['close'] >= r['c2D'] * 0.98):
                i += 1; continue
            N, O = r['c2D'], r['c1W']; res = None
            for j in range(i + 1, min(i + M, len(days) - 1) + 1):
                rj = R(T, j)
                if rj and rj['close'] < O: res = j; break
                held_ok = True
            if res is not None:
                Bv.append(ev(T, res, setup=days[i], O=O, lag_days=res - i))
            i = (res if res is not None else i + M) + 1
    return Bv
for b in (0.03, 0.02):
    B10 = runB(b, 10); B3 = runB(b, 3)
    fast = [e for e in B10 if e['lag_days'] <= 3]; slow = [e for e in B10 if e['lag_days'] > 3]
    print(f'\n== node 门槛 2D ≥ 1W×{1+b:.2f}')
    for lab, E in (('3 天内失守 (M=3)', B3), ('10 天内任何时候失守', B10), ('  其中 4–10 天才失守', slow)):
        print(f'{lab}')
        for k in (1, 3, 5): print(f'   {k}D {wr(E, k)}')
        print(f'   持有到收盘站回旧 core / 满 10 天: {hold(E, "old core")}')
        print(f'   持有到收盘站回当天 2D（v3 口径）: {hold(E, "2D")}')
