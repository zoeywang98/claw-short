#!/usr/bin/env python3
"""Save the UW site's dark pool price levels, one table per session, into history/dp_levels_site (uwsf/sitestore.py).

ZZ 2026-11-22: "这个你只要每天跑，保存在本地，就可以了吧，不用依赖api". The site only serves windows ending on its
latest session, so this keeps the earlier days: day_range 0..K from the logged-in UW tab in DICloak, differenced into
single sessions (day_range k minus k-1), saved. Every saved session is compared with the API's table for the same day
(cache, or a fresh fetch for the latest session); a difference @ZZ in #claw-short (uwsf/dpalert.py).

Runs every weekday at 20:30 ET (daily_short/site_capture.sh, automation "claw-short 暗池网站存档"): after-hours
trading ends at 20:00, so every request sees the same tape. It refuses to run while the latest session is still live.

    python3 site_capture.py                    # watchlist + dpzone focus / zone names, K = 1 (latest + the one before)
    python3 site_capture.py --backfill 21      # 22 sessions at once (the 1M window plus its D-21 snapshot)
    python3 site_capture.py --tickers NVDA --no-alert --dry-run
"""
import argparse
import json
import os
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from uwsf import dpalert, sitestore  # noqa: E402
from uwsf import watchlist as W  # noqa: E402
from uwsf.client import UWClient, load_token  # noqa: E402
from uwsf.layers import NY, Calendar, Config, Ctx, _levels, compare_levels, rows_of  # noqa: E402
from uwsf.uwweb import UWWeb, WebUnavailable, dark_levels_path  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DPZONE = os.path.join(os.path.dirname(HERE), "daily_short", "dpzone")


def default_tickers():
    out = list(W.tickers_of(W.WATCHLIST))
    for f in ("focus.json", "zones.json"):
        try:
            for z in json.load(open(os.path.join(DPZONE, f))):
                if z.get("ticker") and z["ticker"] not in out:
                    out.append(z["ticker"])
        except (OSError, ValueError):
            pass
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="site_capture.py")
    ap.add_argument("--tickers", default="", help="comma-separated (default: watchlist + dpzone focus.json / zones.json)")
    ap.add_argument("--backfill", type=int, default=1, help="K: save the latest K + 1 sessions (default 1)")
    ap.add_argument("--no-alert", action="store_true", help="don't @ZZ on a DICloak / API difference")
    ap.add_argument("--dry-run", action="store_true", help="compare only, save nothing")
    a = ap.parse_args(argv)
    tickers = [t.strip().upper() for t in a.tickers.split(",") if t.strip()] or default_tickers()
    K = max(0, min(a.backfill, 60))

    client = UWClient(load_token())
    cal = Calendar.from_ohlc(client.get("/api/stock/SPY/ohlc/1d", {"timeframe": "1Y"}).body)
    latest, now = cal.latest(), datetime.now(NY)
    today = now.date().isoformat()
    if not sitestore.session_over(latest, now):
        print(f"{now:%Y-%m-%d %H:%M} ET: the {latest} session is not over (after-hours end 20:00); nothing saved")
        return 0
    sessions = cal.window(latest, K + 1)
    web = UWWeb()
    raw = tempfile.mkdtemp(prefix="site_capture_")   # the API envelopes of this run (cache/ is the real store)
    items, problems = [], []
    print(f"{now:%Y-%m-%d %H:%M} ET · latest session {latest} · {len(sessions)} sessions back to {sessions[0]} · "
          f"{len(tickers)} names")
    for T in tickers:
        try:
            got = web.finish(web.start({f"r{k}": dark_levels_path(T, k) for k in range(len(sessions))}), timeout=90)
        except WebUnavailable as e:
            print(f"❌ DICloak unavailable: {e}")
            return 2
        errs = {k: r["error"] for k, r in got.items() if r["error"]}
        dates = {(r["body"] or {}).get("date") for r in got.values() if not r["error"]}
        if errs or dates != {latest}:
            why = "; ".join(f"{k}: {v}" for k, v in list(errs.items())[:2]) or f"site's latest session {sorted(map(str, dates))}"
            print(f"⚠ {T}: skipped ({why})")
            problems.append(T)
            continue
        ranges = {int(k[1:]): _levels(r["body"].get("data") or []) for k, r in got.items()}
        fetched = next(iter(got.values()))["fetched_at"]
        one, bad = sitestore.singles(ranges, sessions)
        ctx = Ctx(client, T, latest, cal, Config(), raw, os.path.join(HERE, "cache"), today)
        same, diff = [], []
        for d, lv in sorted(one.items()):
            api = _levels(rows_of(ctx.get(f"darkpool_levels_{d}", f"/api/darkpool/{T}/price-levels", {"date": d},
                                          cache_date=d)))
            c = compare_levels(api, lv)
            (same if c["match"] else diff).append(d)
            if not c["match"]:
                items.append(dpalert.item(T, "day", d, c))
        changed = [] if a.dry_run else sitestore.put(
            T, {d: (lv, fetched, "day_range 0" if d == latest else
                    f"day_range {len(sessions) - 1 - sessions.index(d)}-{len(sessions) - 2 - sessions.index(d)}")
                for d, lv in one.items()})
        line = f"{'✅' if not diff and not bad else '⚠'} {T}: {len(one)} sessions" + \
               (" (dry run)" if a.dry_run else f" saved, {len(changed)} new or changed") + \
               f" · = API {len(same)}/{len(one)}"
        if diff:
            line += f" · != API: {', '.join(diff)}"
        if bad:
            line += " · not saved: " + "; ".join(f"{d} {w}" for d, w in sorted(bad.items()))
        print(line)
    if items and not a.no_alert:
        note = dpalert.notify_items(items, datetime.now(NY))
        if note:
            print(note)
    print(f"done · {len(tickers) - len(problems)}/{len(tickers)} names · {len(items)} sessions differ from the API · "
          f"UW API requests {client.network_requests}, cache hits {client.cache_hits}")
    return 1 if (problems or items) else 0


if __name__ == "__main__":
    sys.exit(main())
