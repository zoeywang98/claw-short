#!/usr/bin/env python3
"""Intraday single-name rerun (ZZ 2026-10-14): live fetch → brief → analyze.py with today's rules → a short post
(conclusion, positioning, invalidation lines). watch.py launches it when a name crosses one of its decision lines.

The market brief (breaker board, cross-section) is reused from the newest analysis_data/<D>_HHMM run of the day, else
the last post-close scan. Fetched data is relabelled runs/tickers/<T>/<D>_HHMM, so the 17:00 scan starts clean; the new
reply and its watch lines land in logs/<D>_HHMM/, where watch.py picks them up.

usage: rerun.py T [T ...] [--reason TEXT] [--dry-run]
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(HERE)
FETCH = os.path.join(WS, "uw_short_fetch")
sys.path.insert(0, HERE)
sys.path.insert(0, FETCH)
import analyze  # noqa: E402
from uwsf import layers as L  # noqa: E402


def market_brief(D):
    """Newest intraday market brief of D, else the newest post-close one before D."""
    today = sorted(glob.glob(os.path.join(WS, "analysis_data", f"{D}_[0-9][0-9][0-9][0-9]", "market_brief.json")),
                   key=os.path.getmtime)
    if today:
        return today[-1]
    scans = sorted(p for p in glob.glob(os.path.join(WS, "analysis_data", "*", "market_brief.json"))
                   if re.fullmatch(r"\d{4}-\d{2}-\d{2}", os.path.basename(os.path.dirname(p)))
                   and os.path.basename(os.path.dirname(p)) < D)
    return scans[-1] if scans else None


def section(text, head):
    """The '**head**…' block of a reply, up to the next bold heading at line start."""
    m = re.search(r"^\*\*" + re.escape(head) + r"[^\n]*(?:\n(?!\*\*).*)*", text, re.M)
    return m.group(0).strip() if m else ""


def one(T, D, label, mb, reason, dry):
    runs = os.path.join(FETCH, "runs", "tickers", T)
    if os.path.exists(os.path.join(runs, D)):
        return T, f"❌ runs/tickers/{T}/{D} already exists"
    f = subprocess.run(["python3", "fetch.py", "--quiet", "--tickers", T, "--date", D, "--out", runs],
                       cwd=FETCH, capture_output=True, text=True, timeout=600)
    b = subprocess.run(["python3", "brief.py", "--date", D, "--data", runs, "--tickers", T, "--no-market"],
                       cwd=FETCH, capture_output=True, text=True, timeout=300)
    src = os.path.join(runs, D, T, "brief.json")
    if b.returncode != 0 or not os.path.exists(src):
        if os.path.exists(os.path.join(runs, D)):   # never leave a half-fetched <D> dir for the 17:00 scan
            os.rename(os.path.join(runs, D), os.path.join(runs, f"{label}_failed"))
        return T, f"❌ fetch/brief failed: {(f.stderr + b.stderr)[-300:]}"
    an = os.path.join(WS, "analysis_data", label)
    os.makedirs(an, exist_ok=True)
    shutil.copy(src, os.path.join(an, f"{T}.json"))
    if not os.path.exists(os.path.join(an, "market_brief.json")):
        shutil.copy(mb, os.path.join(an, "market_brief.json"))
    os.rename(os.path.join(runs, D), os.path.join(runs, label))
    p = subprocess.run(["python3", os.path.join(HERE, "analyze.py"), "--date", label, "--ticker", T,
                        "--brief", os.path.join(an, f"{T}.json"), "--market-brief", os.path.join(an, "market_brief.json"),
                        "--dry-run"], capture_output=True, text=True, timeout=1500)
    try:
        r = json.load(open(os.path.join(HERE, "logs", label, f"{T}.reply.json")))
    except (OSError, ValueError):
        r = {}
    if p.returncode != 0 or not r.get("result"):
        return T, f"❌ analysis failed: {p.stderr[-300:]}"
    text = analyze.split_watch(r["result"])[0]
    m = re.search(r"\*\*结论\*\*[:：]\s*(.*)", text)
    mb_from = os.path.basename(os.path.dirname(mb))
    post = "\n".join(x for x in [
        f"**{T} 盘中重跑** · {label[-4:-2]}:{label[-2:]} ET · 起因：{reason}",
        f"**结论**：{m.group(1).strip() if m else '未明确'}",
        section(text, "仓位"), section(text, "失效位"),
        f"（熔断 / 板块数据沿用 {mb_from}；完整报告 logs/{label}/{T}.reply.json）"] if x)
    if not dry:
        try:
            analyze.post(post)
        except subprocess.SubprocessError as e:
            return T, f"⚠ analysed but post failed: {e}"
    return T, post


def main(argv=None):
    ap = argparse.ArgumentParser(prog="rerun.py")
    ap.add_argument("tickers", nargs="+")
    ap.add_argument("--reason", default="手动")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    now = datetime.now(L.NY)
    D, label = now.date().isoformat(), f"{now:%Y-%m-%d_%H%M}"
    mb = market_brief(D)
    if not mb:
        print("❌ no market brief to reuse")
        return 1
    reasons = dict(x.split("=", 1) for x in a.reason.split(";") if "=" in x)   # per-ticker "T=reason;U=reason"
    with ThreadPoolExecutor(max_workers=4) as ex:
        results = list(ex.map(lambda T: one(T, D, label, mb, reasons.get(T, a.reason), a.dry_run), a.tickers))
    for T, out in results:
        print(f"== {T}\n{out}\n")
    return 0 if all(not out.startswith("❌") for _, out in results) else 1


if __name__ == "__main__":
    sys.exit(main())
