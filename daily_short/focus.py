#!/usr/bin/env python3
"""Post-close read of the 重点 names that are not on the 23-name watchlist (ZZ 2026-11-19 "googl meta", right after
asking to monitor the Visa / VRT dark-pool zone patterns).

run.sh calls this after the summary. Each dpzone/focus.json ticker that is off the watchlist gets the same read as a
scan name: fetch -> brief -> analyze.py -> chart + report. It uses the scan's market brief but stays out of the
board, the cross-section, the summary, watch.py and the reviews. Data goes to analysis_data/<D>-focus/ and replies
to logs/<D>-focus/. dpzone.py watches the report's Dark Pool zone the next day. Watchlist names in focus.json
(META) need nothing here; dpzone.py takes their zone from the scan itself.

usage: focus.py --date D --market-brief PATH [--dry-run]
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(HERE)
FETCH = os.path.join(WS, "uw_short_fetch")
FINVIZ = "/Users/yuwang/.openclaw/workspace-claw-general/finviz/fv_short_interest.py"
sys.path.insert(0, FETCH)
from uwsf.watchlist import WATCHLIST, tickers_of  # noqa: E402


def focus_tickers():
    try:
        return [z["ticker"] for z in json.load(open(os.path.join(HERE, "dpzone", "focus.json")))]
    except (OSError, ValueError, KeyError, TypeError):
        return []


def main(argv=None):
    ap = argparse.ArgumentParser(prog="focus.py")
    ap.add_argument("--date", required=True)
    ap.add_argument("--market-brief", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    names = [T for T in focus_tickers() if T not in set(tickers_of(WATCHLIST))]
    if not names:
        print("no off-watchlist focus names")
        return 0
    label = f"{a.date}-focus"
    an, log = os.path.join(WS, "analysis_data", label), os.path.join(HERE, "logs", label)
    os.makedirs(an, exist_ok=True)
    os.makedirs(log, exist_ok=True)
    shutil.copy(a.market_brief, os.path.join(an, "market_brief.json"))
    with open(os.path.join(log, "_finviz.out"), "w") as fh:   # 空头闸 SI line; a failure only makes it say 没拉到
        subprocess.run(["python3", FINVIZ, *names, "--rows", "1", "--out-dir", os.path.join(FETCH, "finviz_si")],
                       stdout=fh, stderr=subprocess.STDOUT, timeout=600)
    rc = 0
    for T in names:
        runs = os.path.join(FETCH, "runs", "tickers", T)
        with open(os.path.join(log, f"{T}.fetch.out"), "w") as fh:
            subprocess.run(["python3", "fetch.py", "--quiet", "--tickers", T, "--date", a.date, "--out", runs],
                           cwd=FETCH, stdout=fh, stderr=subprocess.STDOUT, timeout=900)
        with open(os.path.join(log, f"{T}.brief.out"), "w") as fh:
            b = subprocess.run(["python3", "brief.py", "--date", a.date, "--data", runs, "--tickers", T, "--no-market"],
                               cwd=FETCH, stdout=fh, stderr=subprocess.STDOUT, timeout=600)
        src = os.path.join(runs, a.date, T, "brief.json")
        if b.returncode or not os.path.exists(src):
            print(f"❌ {T} focus brief (see logs/{label}/{T}.brief.out)")
            rc = 1
            continue
        shutil.copy(src, os.path.join(an, f"{T}.json"))
        with open(os.path.join(log, f"{T}.err"), "w") as fh:
            p = subprocess.run(["python3", os.path.join(HERE, "analyze.py"), "--date", label, "--ticker", T,
                                "--brief", os.path.join(an, f"{T}.json"),
                                "--market-brief", os.path.join(an, "market_brief.json"),
                                "--holding-suffix=-focus", *(["--dry-run"] if a.dry_run else [])],
                               stderr=fh, timeout=1500)
        print(f"{'✅' if p.returncode == 0 else '❌'} {T} (focus)")
        rc = rc or p.returncode
    return rc


if __name__ == "__main__":
    sys.exit(main())
