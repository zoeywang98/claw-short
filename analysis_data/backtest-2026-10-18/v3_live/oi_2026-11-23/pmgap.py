import json, os, glob, re, statistics as st
WS = "/Users/yuwang/.openclaw/workspace-claw-short"
bars = {}
for d in sorted(glob.glob(WS + "/analysis_data/2026-*")):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", os.path.basename(d)):
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
            if x and x[0] <= os.path.basename(d):
                bars.setdefault(T, {})[x[0]] = (x[1], x[4])
days = sorted({d for v in bars.values() for d in v})
rows = []
for d in sorted(glob.glob(WS + "/analysis_data/2026-*_premarket")):
    D = os.path.basename(d)[:10]
    if D < "2026-10-19" or D not in days:
        continue
    i = days.index(D)
    for f in glob.glob(d + "/*.json"):
        T = os.path.basename(f)[:-5]
        j = json.load(open(f))
        v = j.get("last_night_verdict") or ""
        pm = j.get("premarket") or {}
        w = ((j.get("last_night_structure") or {}).get("darkpool_windows") or {})
        c2d = (w.get("2D") or {}).get("centroid_top8")
        prev = pm.get("prev_close")
        bt = bars.get(T, {})
        if not (c2d and prev and D in bt):
            continue
        o = bt[D][0]
        def cl(k):
            return bt[days[i + k]][1] if i + k < len(days) and days[i + k] in bt else None
        rows.append(dict(D=D, T=T, short=v.startswith("✅"), held="持有" in v, pm=pm.get("last"), c2d=c2d,
                         prev=prev, o=o, c={k: cl(k) for k in (0, 2, 4)}))
def ret(r, k, base):
    c = r["c"][k]
    return (c / r[base] - 1) if c else None
board = {}
for k in (0, 2, 4):
    for base in ("o", "prev"):
        for D in {r["D"] for r in rows}:
            xs = [ret(r, k, base) for r in rows if r["D"] == D and ret(r, k, base) is not None]
            board[(D, k, base)] = st.mean(xs) if xs else None
def show(name, sel, base):
    out = [name]
    for k, lab in ((0, "当天"), (2, "3天"), (4, "5天")):
        xs = [(ret(r, k, base), ret(r, k, base) - board[(r["D"], k, base)]) for r in sel if ret(r, k, base) is not None]
        if not xs:
            continue
        n = len(xs)
        out.append(f"{lab} n{n} 均{st.mean(a for a, _ in xs)*100:+.1f}% 超额{st.mean(e for _, e in xs)*100:+.1f} 跑输{sum(e < 0 for _, e in xs)/n*100:.0f}% 跌{sum(a < 0 for a, _ in xs)/n*100:.0f}%")
    print(" | ".join(out))
S = [r for r in rows if r["short"]]
print("premarket days:", sorted({r['D'] for r in rows})[0], "→", sorted({r['D'] for r in rows})[-1], "rows", len(rows), "✅", len(S))
for base, bl in (("o", "从开盘算"), ("prev", "从前收算")):
    print("==", bl)
    show("✅ 盘前≥2D", [r for r in S if r["pm"] and r["pm"] >= r["c2d"]], base)
    show("✅ 盘前<2D", [r for r in S if r["pm"] and r["pm"] < r["c2d"]], base)
    show("✅ 开盘≥2D", [r for r in S if r["o"] >= r["c2d"]], base)
    show("✅ 开盘<2D", [r for r in S if r["o"] < r["c2d"]], base)
    show("✅ 高开≥3%且开盘≥2D", [r for r in S if r["o"] / r["prev"] - 1 >= 0.03 and r["o"] >= r["c2d"]], base)
    show("⚪ 全部", [r for r in rows if not r["short"]], base)
