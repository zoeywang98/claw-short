#!/usr/bin/env python3
"""Charts for the dark-pool zone tallies (ZZ 2026-11-12 "要": every 11:30 / 13:30 / 15:30 tally also posts the
4-card DP migration chart, 1M / 1W / 2D / 当天新增, of each zone's ticker).

dpzone.py launches this detached right after the tally text is posted, so the 5-minute cron job's timeout never
cuts it off. Per ticker:
  - live fetch.py into /tmp/dpzone_charts/, never into uw_short_fetch/runs/, so the 17:00 scan's dirs stay untouched;
  - brief.py;
  - dp_chart.py --asof HH:MM (盘中 / 现价 labels);
  - post the PNG with the zone ranges in the caption.
A failure only logs and skips that ticker. PNGs go to media/dp_charts/<D>_zone/<HHMM>/ (media/ is gitignored).

The zone is shaded on every card; the 当天新增 card and the caption say how much dark volume the zone took today and
since the previous tally (Olivia 2026-11-12 "新增多少可以标记出来"; numbers passed in by dpzone.py, the same as the tally).

usage: dpzone_chart.py --time HH:MM --zones '[["V", "Visa", 425, 430, "dist", vol, new, "13:30"], ...]' [--dry-run]
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(WS, "uw_short_fetch"))
import analyze  # noqa: E402
from uwsf import layers as L  # noqa: E402

FETCH_DIR = "/tmp/dpzone_charts"
KIND = {"dist": "派发观察区", "accum": "承接观察区"}


def wan(v):
    return f"{v / 1e4:.1f}万" if v >= 1e4 else f"{v:,.0f}"


def one(T, D, hhmm, ranges, zone_args, dry):
    out = os.path.join(FETCH_DIR, f"{D}_{hhmm.replace(':', '')}", T)
    shutil.rmtree(out, ignore_errors=True)
    f = os.path.join(WS, "uw_short_fetch")
    subprocess.run([sys.executable, "fetch.py", "--quiet", "--tickers", T, "--date", D, "--out", out],
                   cwd=f, timeout=900, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not os.path.isdir(os.path.join(out, D)):   # fetch.py falls back to the last session when D has none yet
        raise RuntimeError(f"no {D} fetch (got {os.listdir(out) if os.path.isdir(out) else 'nothing'})")
    subprocess.run([sys.executable, "brief.py", "--date", D, "--data", out, "--tickers", T, "--no-market"],
                   cwd=f, timeout=900, check=True, capture_output=True)
    png = os.path.join(analyze.CHART_DIR, f"{D}_zone", hhmm.replace(":", ""), f"{T}.png")
    os.makedirs(os.path.dirname(png), exist_ok=True)
    p = subprocess.run([analyze.PY_CHART, os.path.join(HERE, "dp_chart.py"), "--brief",
                        os.path.join(out, D, T, "brief.json"), "--out", png, "--asof", hhmm,
                        *[x for z in zone_args for x in ("--zone", z)]],
                       capture_output=True, text=True, timeout=300)
    if p.returncode or not os.path.exists(png):
        raise RuntimeError(f"chart: {(p.stderr or p.stdout).strip()[-300:]}")
    caption = f"**{T}** 暗池灰色重心迁移（1M / 1W / 2D / 当天新增）· {hhmm} ET 盘中 · " + "；".join(ranges)
    print(f"{T} -> {png} | {caption}")
    if not dry:
        analyze.post_chart(png, caption)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="dpzone_chart.py")
    ap.add_argument("--time", required=True, help="tally time HH:MM ET (chart label)")
    ap.add_argument("--zones", required=True, help='JSON [[ticker, name, lo, hi, kind], ...]')
    ap.add_argument("--dry-run", action="store_true", help="draw, do not post")
    a = ap.parse_args(argv)
    D = datetime.now(L.NY).date().isoformat()
    by_t, zargs = {}, {}
    for T, name, lo, hi, kind, *rest in json.loads(a.zones):
        vol, new, since = (rest + [None, None, ""])[:3]
        amt = "" if vol is None else f"今天 {wan(vol)}" + (f"（{since} 以来 +{wan(new)}）" if since and new is not None
                                                           else "")
        by_t.setdefault(T, []).append(f"{name} {lo:g}–{hi:g} {KIND.get(kind, kind)}" + (f"：{amt}" if amt else ""))
        zargs.setdefault(T, []).append(f"{lo:g},{hi:g},{lo:g}–{hi:g} {amt}".rstrip())
    rc = 0
    for T, ranges in by_t.items():   # zones.json order, one chart per ticker
        try:
            one(T, D, a.time, ranges, zargs[T], a.dry_run)
        except Exception as e:   # noqa: BLE001 - one ticker failing must not stop the others
            print(f"⚠ {T} {datetime.now(L.NY):%H:%M}: {e}", file=sys.stderr)
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
