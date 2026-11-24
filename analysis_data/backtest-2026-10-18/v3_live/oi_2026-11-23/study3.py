import sys, re, json, statistics as st
sys.argv = ["x"]
import io, contextlib
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    exec(open("/Users/yuwang/.openclaw/workspace-claw-short/analysis_data/backtest-2026-10-18/v3_live/oi_2026-11-23/study2.py").read())
S = [r for r in rows if r["short"]]
for key, nm in (("S3", "帖子读法"), ("S4", "机械复算")):
    a = [r for r in S if r[key] == "偏空"]
    b = [r for r in S if r[key] and r[key] != "偏空"]
    line(f"{nm} 偏空", a); line(f"{nm} 其他", b)
    line(f"{nm} 偏空·去重", first_of_run(a, key)); line(f"{nm} 其他·去重", first_of_run(b, key))
line("全部 ✅", S)
for lo, hi in (("2026-10-19", "2026-11-04"), ("2026-11-05", "2026-11-20")):
    line(f"{lo[5:]}–{hi[5:]} 帖子 偏空", [r for r in S if lo <= r["D"] <= hi and r["S3"] == "偏空"])
    line(f"{lo[5:]}–{hi[5:]} 帖子 其他", [r for r in S if lo <= r["D"] <= hi and r["S3"] and r["S3"] != "偏空"])
print("今早 11-23：", end="")
import glob, os
out = {}
for f in sorted(glob.glob(f"{WS}/daily_short/logs/2026-11-23_premarket/*.reply.json")):
    T = os.path.basename(f).split(".")[0]
    txt = json.load(open(f)).get("result") or ""
    v = re.search(r"\*\*结论\*\*：(.*)", txt).group(1)
    if "→ 今早 ✅" not in v:
        continue
    out.setdefault(model_label("2026-11-23", T), []).append(T)
print(" · ".join(f"{k}: {' '.join(v)}" for k, v in out.items()))
