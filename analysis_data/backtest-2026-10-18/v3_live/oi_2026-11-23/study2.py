import json, statistics as st, sys
sys.path.insert(0, "/Users/yuwang/.openclaw/workspace-claw-short/analysis_data/backtest-2026-10-18/v3_live/oi_2026-11-23")
from base import *   # rows, bars, days, model_label ...
WL = sorted({r["T"] for r in rows})
P = json.load(open(f"{WS}/analysis_data/backtest-2026-10-18/prices.json"))
names = [T for T in WL if T in P]
pd = sorted(set.intersection(*[set(P[T]) for T in names]))
pd = [d for d in pd if "2026-07-17" <= d <= "2026-10-16"]
R = {T: [P[T][pd[i]][3] / P[T][pd[i - 1]][3] - 1 for i in range(1, len(pd))] for T in names}
M = [st.mean(R[T][i] for T in names) for i in range(len(pd) - 1)]
vm, mm = st.pvariance(M), st.mean(M)
BETA = {T: sum((r - st.mean(R[T])) * (m - mm) for r, m in zip(R[T], M)) / len(M) / vm for T in names}

def replica(D, T):
    """the model's rule mechanically: last night's 1–2 biggest single-leg flow contracts (dte>=2), did they become new OI, which side"""
    j = json.load(open(f"{WS}/analysis_data/{D}_premarket/{T}.json"))
    oi = j.get("next_day_oi") or {}
    rowsoi = {r["sym"]: r for r in (oi.get("at_levels_and_flow_contracts") or []) + (oi.get("top_increase") or []) + (oi.get("top_decrease") or [])}
    tc = ((j.get("last_night_structure") or {}).get("option_trades") or {}).get("top_contracts") or []
    labs = []
    for c in sorted(tc, key=lambda c: -((c.get("ask_premium") or 0) + (c.get("bid_premium") or 0))):
        if (c.get("expiry") or "") <= D:
            continue
        r = rowsoi.get(c["sym"])
        if r and (r.get("prev_multi_leg_volume") or 0) > 0.5 * max(r.get("volume") or 0, 1):
            continue
        a, b = c.get("ask_premium") or 0, c.get("bid_premium") or 0
        side = "buy" if a > 1.5 * b else "sell" if b > 1.5 * a else None
        d = (r or {}).get("oi_diff") or 0
        if d < 0:
            labs.append("平仓")
        elif d == 0 or not side:
            labs.append("看不出")
        else:
            labs.append({("put", "buy"): "put 买开", ("call", "sell"): "call 写开", ("call", "buy"): "call 买开", ("put", "sell"): "put 写开"}[(c["type"], side)])
        if len(labs) == 2:
            break
    L = set(labs)
    if not L:
        return None
    b, u = bool(L & BEAR), bool(L & BULL)
    return "偏空" if b and not u else "偏多" if u and not b else "混合" if b and u else "平仓/看不出"

for r in rows:
    r["S4"] = replica(r["D"], r["T"]) if r["v3"] else None
board = {}
for D in {r["D"] for r in rows}:
    for k in (0, 2, 4):
        xs = [r["c"][k] / r["o"] - 1 for r in rows if r["D"] == D and r["c"][k]]
        board[(D, k)] = st.mean(xs) if xs else None

def stats(sel, k):
    xs = []
    for r in sel:
        if not r["c"][k] or r["T"] not in BETA:
            continue
        x = r["c"][k] / r["o"] - 1
        xs.append((x - board[(r["D"], k)], x - BETA[r["T"]] * board[(r["D"], k)]))
    return xs

def line(name, sel):
    out = [name]
    for k, lab in ((2, "3天"), (4, "5天")):
        xs = stats(sel, k)
        if len(xs) < 8:
            out.append(f"{lab} n{len(xs)}"); continue
        n = len(xs)
        out.append(f"{lab} n{n} 跑输{sum(e < 0 for e, _ in xs)/n*100:.0f}% 超额{st.mean(e for e, _ in xs)*100:+.1f} · β后跑输{sum(b < 0 for _, b in xs)/n*100:.0f}% β超额{st.mean(b for _, b in xs)*100:+.1f}")
    out.append(f"{len({r['T'] for r in sel})}只票")
    print(" | ".join(out))

def first_of_run(sel, key):
    """same name, same reading on consecutive premarket days -> keep only the first day"""
    by = {}
    for r in sorted(rows, key=lambda r: (r["T"], r["D"])):
        by.setdefault(r["T"], []).append(r)
    keep = set()
    for T, rs in by.items():
        prev = None
        for r in rs:
            if r[key] != prev:
                keep.add((r["T"], r["D"]))
            prev = r[key]
    return [r for r in sel if (r["T"], r["D"]) in keep]

S = [r for r in rows if r["short"]]
W = [r for r in rows if r["v3"] and not r["short"]]
for key, nm in (("S3", "帖子里的读法"), ("S4", "按同一口径机械复算")):
    print(f"== ✅ · {nm}")
    for g in ("偏空", "偏多", "平仓/看不出", "混合"):
        line(f"OI {g}", [r for r in S if r[key] == g])
    print(f"   -- 同一只票连续同一读法只算第一天")
    for g in ("偏空", "偏多", "平仓/看不出"):
        line(f"OI {g}", first_of_run([r for r in S if r[key] == g], key))
print("== ⚪（不做空的票）· 帖子里的读法")
for g in ("偏空", "偏多", "平仓/看不出"):
    line(f"OI {g}", [r for r in W if r["S3"] == g])
print("== 帖子读法 vs 机械复算 一致率（✅）")
both = [r for r in S if r["S3"] and r["S4"]]
print(f"n{len(both)} 一致 {sum(r['S3'] == r['S4'] for r in both)/len(both)*100:.0f}%")
print("== 同一只票内比较（✅，帖子读法，5天 β超额：偏空日均值 − 偏多日均值）")
diffs = []
for T in sorted({r["T"] for r in S}):
    a = [b for e, b in stats([r for r in S if r["T"] == T and r["S3"] == "偏空"], 4)]
    u = [b for e, b in stats([r for r in S if r["T"] == T and r["S3"] in ("偏多", "平仓/看不出")], 4)]
    if a and u:
        diffs.append((T, st.mean(a) - st.mean(u), len(a), len(u)))
print(" ".join(f"{T}{d*100:+.1f}({na}/{nu})" for T, d, na, nu in diffs))
print(f"{sum(d < 0 for _, d, _, _ in diffs)}/{len(diffs)} 只票偏空日更差（对空头更好）· 中位数 {st.median(d for _, d, _, _ in diffs)*100:+.1f}")
