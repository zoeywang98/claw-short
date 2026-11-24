import json, os, glob, re, statistics as st
WS = "/Users/yuwang/.openclaw/workspace-claw-short"
bars = {}
for d in sorted(glob.glob(WS + "/analysis_data/2026-*")):
    dn = os.path.basename(d)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", dn):
        continue
    for f in glob.glob(d + "/*.json"):
        T = os.path.basename(f)[:-5]
        if T == "market_brief":
            continue
        try:
            b = json.load(open(f))
        except Exception:
            continue
        for x in (b.get("price") or {}).get("last_22_bars") or []:
            if x and x[0] <= dn:
                bars.setdefault(T, {})[x[0]] = (x[1], x[4])
days = sorted({d for v in bars.values() for d in v})
BEAR, BULL = {"put 买开", "call 写开"}, {"call 买开", "put 写开"}
LAB = re.compile(r"→\s*(put 买开|call 写开|call 买开|put 写开|平仓|看不出)")

def model_label(D, T):
    p = f"{WS}/daily_short/logs/{D}_premarket/{T}.reply.json"
    try:
        txt = json.load(open(p)).get("result") or ""
    except Exception:
        return None
    sec = txt.split("Options Flow", 1)[1].split("Dealer Positioning", 1)[0] if "Options Flow" in txt else ""
    L = set(LAB.findall(sec))
    if not L:
        return None
    b, u = bool(L & BEAR), bool(L & BULL)
    return "偏空" if b and not u else "偏多" if u and not b else "混合" if b and u else "平仓/看不出"

def flow_signal(oi):
    seen, bear, bull = set(), 0.0, 0.0
    for r in (oi.get("top_increase") or []) + (oi.get("at_levels_and_flow_contracts") or []):
        if r.get("sym") in seen:
            continue
        seen.add(r.get("sym"))
        d, vol = r.get("oi_diff") or 0, r.get("volume") or 0
        if d <= 0 or vol <= 0 or (r.get("dte") or 0) < 2 or (r.get("prev_multi_leg_volume") or 0) > 0.5 * vol:
            continue
        a, bb = r.get("prev_ask_volume") or 0, r.get("prev_bid_volume") or 0
        side = "buy" if a > 1.2 * bb else "sell" if bb > 1.2 * a else None
        if not side:
            continue
        w = (r.get("prev_total_premium") or 0) * min(1.0, d / vol)
        if (r["type"] == "put") == (side == "buy"):
            bear += w
        else:
            bull += w
    if bear + bull <= 0:
        return None
    net = (bear - bull) / (bear + bull)
    return "偏空" if net >= 0.3 else "偏多" if net <= -0.3 else "混合"

def totals_signal(oi):
    t = oi.get("totals") or {}
    c, p = t.get("call_oi_diff"), t.get("put_oi_diff")
    if c is None or p is None:
        return None
    return "put增call平降" if p > 0 and c <= 0 else "call增put平降" if c > 0 and p <= 0 else "都增" if c > 0 else "都降"

rows = []
for d in sorted(glob.glob(WS + "/analysis_data/2026-*_premarket")):
    D = os.path.basename(d)[:10]
    if D < "2026-09-29" or D not in days:
        continue
    i = days.index(D)
    for f in glob.glob(d + "/*.json"):
        T = os.path.basename(f)[:-5]
        j = json.load(open(f))
        bt = bars.get(T, {})
        if D not in bt:
            continue
        oi = j.get("next_day_oi") or {}
        if oi.get("status") == "missing":
            continue
        v = j.get("last_night_verdict") or ""
        w = (j.get("last_night_structure") or {}).get("darkpool_windows") or {}
        o = bt[D][0]
        rows.append(dict(D=D, T=T, v3=D >= "2026-10-19", short=D >= "2026-10-19" and v.startswith("✅"),
                         pm=(j.get("premarket") or {}).get("last"), c2d=(w.get("2D") or {}).get("centroid_top8"),
                         o=o, c={k: (bt[days[i + k]][1] if i + k < len(days) and days[i + k] in bt else None) for k in (0, 2, 4)},
                         S3=model_label(D, T) if D >= "2026-10-19" else None, S2=flow_signal(oi), S1=totals_signal(oi)))
board = {}
for D in {r["D"] for r in rows}:
    for k in (0, 2, 4):
        xs = [r["c"][k] / r["o"] - 1 for r in rows if r["D"] == D and r["c"][k]]
        board[(D, k)] = st.mean(xs) if xs else None

def line(name, sel):
    out = [f"{name}"]
    for k, lab in ((0, "当天"), (2, "3天"), (4, "5天")):
        xs = [(r["c"][k] / r["o"] - 1, r["c"][k] / r["o"] - 1 - board[(r["D"], k)]) for r in sel if r["c"][k]]
        if len(xs) < 8:
            out.append(f"{lab} n{len(xs)}")
            continue
        n = len(xs)
        out.append(f"{lab} n{n} 超额{st.mean(e for _, e in xs)*100:+.1f} 跑输{sum(e < 0 for _, e in xs)/n*100:.0f}%")
    print(" | ".join(out))

S = [r for r in rows if r["short"]]
print(f"rows {len(rows)}（9/29–11/20 全部票）· ✅ {len(S)}（10/19–11/20）")
print("== ✅，按早上帖子里写的次日 OI 判断（模型读的）")
line("全部 ✅", S)
for g in ("偏空", "偏多", "混合", "平仓/看不出"):
    line(f"OI {g}", [r for r in S if r["S3"] == g])
print("== ✅，按次日 OI 机械算（昨天 ask/bid 方向 × 变成新仓的 premium）")
for g in ("偏空", "偏多", "混合"):
    line(f"OI {g}", [r for r in S if r["S2"] == g])
line("没有可判的新仓", [r for r in S if r["S2"] is None])
print("== ✅，按全链 OI 总量")
for g in ("put增call平降", "call增put平降", "都增", "都降"):
    line(g, [r for r in S if r["S1"] == g])
print("== ✅ 且盘前已站回 2D")
P = [r for r in S if r["pm"] and r["c2d"] and r["pm"] >= r["c2d"]]
line("全部", P)
for g in ("偏空", "偏多"):
    line(f"帖子 OI {g}", [r for r in P if r["S3"] == g])
    line(f"机械 OI {g}", [r for r in P if r["S2"] == g])
print("== 所有票（9/29–11/20），机械 OI")
for g in ("偏空", "偏多", "混合"):
    line(f"OI {g}", [r for r in rows if r["S2"] == g])
print("== 分两段（✅）")
for lo, hi in (("2026-10-19", "2026-11-04"), ("2026-11-05", "2026-11-20")):
    for src in ("S3", "S2"):
        for g in ("偏空", "偏多"):
            line(f"{lo[5:]}–{hi[5:]} {'帖子' if src == 'S3' else '机械'} {g}", [r for r in S if lo <= r["D"] <= hi and r[src] == g])
