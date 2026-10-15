#!/usr/bin/env python3
"""Intraday decision-line alerts (ZZ 2026-10-14). Every few minutes in regular hours: take each name's newest decision
lines (logs/<run>/<T>.watch.json, the ```watch``` block analyze.py / confirm.py cut out of the posted reply), compare
them with the live price from one UW screener call, and post every crossed line once per day to #claw-short. A crossing also re-reads that name with live data
(rerun.py, detached; once per name per day, at most MAX_RERUNS a day, until RERUN_UNTIL).

Lines come from the current cycle only: the last post-close scan before today, its pre-market confirmation and any
intraday rerun (logs/<D>_HHMM); per name the newest file wins. Fired lines are kept in logs/<D>_watch/state.json.

usage: watch.py [--dry-run]      (scheduled every 5 min, 09:00-16:55 ET Mon-Fri; outside 09:30-16:05 it exits)
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, time as dtime

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(WS, "uw_short_fetch"))
import analyze  # noqa: E402
from uwsf import layers as L  # noqa: E402
from uwsf.client import UWClient, load_token  # noqa: E402

LOGS = os.path.join(HERE, "logs")
RUN_DIR = re.compile(r"(\d{4}-\d{2}-\d{2})(_premarket|_\d{4})?")
OPEN, CLOSE = dtime(9, 30), dtime(16, 5)
STALE_S = 20 * 60   # a quote older than this (halt, holiday) is not compared
MAX_RERUNS = 8      # automatic reruns per day (each ≈ $2–5 of Claude, 3–5 min); one per name per day
RERUN_UNTIL = dtime(15, 45)   # later crossings only alert: the 17:00 scan re-reads every name anyway


def source_label(run):
    day, kind = run[5:10], run[10:]
    if kind == "_premarket":
        return f"{day} 盘前确认"
    if kind:
        return f"{day} {kind[1:3]}:{kind[3:]} 盘中重跑"
    return f"{day} 收盘扫描"


def current_lines(D):
    """{ticker: (run dir, [line, ...])} from the newest watch file per ticker in the current cycle."""
    runs = [d for d in os.listdir(LOGS) if RUN_DIR.fullmatch(d)]
    scans = [d for d in runs if len(d) == 10 and d < D]
    if not scans:
        return {}
    start, best = max(scans), {}
    for run in runs:
        if not start <= run[:10] <= D:
            continue
        for f in os.listdir(os.path.join(LOGS, run)):
            if f.endswith(".watch.json"):
                p = os.path.join(LOGS, run, f)
                t, m = f[:-len(".watch.json")], os.path.getmtime(p)
                if t not in best or m > best[t][0]:
                    best[t] = (m, p, run)
    out = {}
    for t, (_, p, run) in best.items():
        try:
            lines = [x for x in json.load(open(p)) if isinstance(x, dict)
                     and isinstance(x.get("price"), (int, float)) and x.get("dir") in ("above", "below")]
        except (OSError, ValueError):
            continue
        if lines:
            out[t] = (run, lines)
    return out


def quotes(client, tickers):
    r = client.get("/api/screener/stocks", {"ticker": ",".join(tickers), "limit": 500})
    rows = r.body.get("data", []) if isinstance(r.body, dict) else []
    return {x["ticker"]: x for x in rows if x.get("ticker")}


def main(argv=None):
    ap = argparse.ArgumentParser(prog="watch.py")
    ap.add_argument("--dry-run", action="store_true", help="print alerts, do not post or record them")
    a = ap.parse_args(argv)

    now = datetime.now(L.NY)
    D = now.date().isoformat()
    if now.weekday() >= 5 or not OPEN <= now.time() <= CLOSE:
        print(f"NO_REPLY outside regular hours ({now:%a %H:%M} ET)")
        return 0
    lines = current_lines(D)
    if not lines:
        print("NO_REPLY no decision lines in the current cycle")
        return 0

    q = quotes(UWClient(load_token()), sorted(lines))
    state_dir = os.path.join(LOGS, f"{D}_watch")
    state_p = os.path.join(state_dir, "state.json")
    state = json.load(open(state_p)) if os.path.exists(state_p) else {}
    fired, reran = set(state.get("fired", [])), list(state.get("rerun", []))
    alerts, new_keys, checked, crossed = [], [], 0, {}
    for t, (run, ls) in sorted(lines.items()):
        x = q.get(t)
        if not x or x.get("date") != D or not x.get("close"):
            continue   # not quoted today (holiday / missing)
        age = now.timestamp() - int(x.get("quote_time") or 0) / 1000
        if age > STALE_S:
            continue
        px = float(x["close"])
        checked += 1
        for ln in ls:
            key = f"{t}|{ln['dir']}|{ln['price']:g}"
            hit = px < ln["price"] if ln["dir"] == "below" else px > ln["price"]
            if hit and key not in fired:
                verb = "跌破" if ln["dir"] == "below" else "站上"
                shown = f"{px:.2f}" if round(px, 2) != round(ln["price"], 2) else f"{px:.3f}"
                alerts.append(f"{t} {shown} {verb} {ln['price']:g}（{ln.get('label') or '判决线'}）· {source_label(run)}")
                new_keys.append(key)
                crossed.setdefault(t, f"{now:%H:%M} {verb} {ln['price']:g}（{ln.get('label') or '判决线'}）")

    # a crossing re-reads the name with live data (rerun.py), at most once per name per day and MAX_RERUNS per day
    rerun = [t for t in crossed if t not in reran][:max(0, MAX_RERUNS - len(reran))] if now.time() <= RERUN_UNTIL else []
    log_line = f"{now:%H:%M} names={len(lines)} quoted={checked} new={len(alerts)} rerun={','.join(rerun) or '-'}"
    if alerts:
        text = (f"**盯线提醒** · {now:%H:%M} ET（现价 = UW 实时成交价）\n" + "\n".join(alerts)
                + (f"\n→ 自动重跑 {' '.join(rerun)}，几分钟后贴结论" if rerun else ""))
        print(text)
        if not a.dry_run:
            try:
                analyze.post(text)
            except subprocess.CalledProcessError as e:
                print(f"⚠ post failed, will retry next run: {e}", file=sys.stderr)
                new_keys = []
            except subprocess.TimeoutExpired:
                log_line += " (send timed out, usually delivered)"
    else:
        print(f"NO_REPLY no new crossings · {log_line}")
    if not a.dry_run:
        os.makedirs(state_dir, exist_ok=True)
        if rerun and new_keys:   # detached: the cron job's own timeout must not kill the analysis
            subprocess.Popen([sys.executable, os.path.join(HERE, "rerun.py"), *rerun,
                              "--reason", ";".join(f"{t}={crossed[t]}" for t in rerun)],
                             cwd=HERE, start_new_session=True, stdin=subprocess.DEVNULL,
                             stdout=open(os.path.join(state_dir, "rerun.log"), "a"), stderr=subprocess.STDOUT)
            reran += rerun
        with open(state_p, "w") as f:
            json.dump({"fired": sorted(fired | set(new_keys)), "rerun": reran}, f, ensure_ascii=False, indent=1)
        with open(os.path.join(state_dir, "watch.log"), "a") as f:
            f.write(log_line + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
