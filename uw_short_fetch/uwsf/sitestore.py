"""Local history of the UW site's dark pool price levels, one table per ticker per session.

ZZ 2026-11-22: "这个你只要每天跑，保存在本地，就可以了吧，不用依赖api". The site only serves windows that end on its
latest session (/api/flow/dark/price_levels/<T>?day_range=k = the latest k + 1 sessions summed), so earlier single
days and windows ending before the latest session have to come from what was saved.

- One past session = day_range k minus day_range k-1 (exact integers). One batch of day_range 0..K, taken while the
  site's latest session is over, gives the last K + 1 sessions. site_capture.py does that every evening (20:30 ET,
  after-hours trading ends 20:00), and once with --backfill to fill the 1M window right away.
- A session is saved only from a quiet site (latest session over, so every request sees the same tape) and only when
  the differences are all >= 0. Whether it equals the API's table is checked when it is used
  (layers.layer_darkpool_levels) and when it is captured (site_capture.py); both @ZZ on a mismatch.
- Store: history/dp_levels_site/<T>.json = {date: {"rows": [[price, dark, regular], ...] (price high to low,
  all-zero buckets dropped), "fetched_at": UTC, "how": "day_range k-(k-1)" or "day_range 0"}}.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, time as dtime
from typing import Any, Dict, List, Optional, Tuple

from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "history", "dp_levels_site")
AFTER_HOURS_END = dtime(20, 0)

Levels = Dict[float, List[float]]


def _path(ticker: str, root: str = DIR) -> str:
    return os.path.join(root, f"{ticker}.json")


def load(ticker: str, root: str = DIR) -> Dict[str, Any]:
    try:
        with open(_path(ticker, root)) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def get(ticker: str, d: str, root: str = DIR) -> Optional[Levels]:
    """The saved site table for one session, or None."""
    rec = load(ticker, root).get(d)
    if not rec:
        return None
    return {float(p): [float(dk), float(rg)] for p, dk, rg in rec["rows"]}


def put(ticker: str, tables: Dict[str, Tuple[Levels, str, str]], root: str = DIR) -> List[str]:
    """Save {date: (levels, fetched_at, how)}; returns the dates whose table is new or changed."""
    data = load(ticker, root)
    changed = []
    for d, (lv, fetched_at, how) in tables.items():
        rows = [[p, v[0], v[1]] for p, v in sorted(lv.items(), reverse=True) if v[0] or v[1]]
        old = data.get(d)
        if not old or old.get("rows") != rows:
            changed.append(d)
        data[d] = {"rows": rows, "fetched_at": fetched_at, "how": how}
    os.makedirs(root, exist_ok=True)
    tmp = _path(ticker, root) + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(dict(sorted(data.items())), fh, separators=(",", ":"))
    os.replace(tmp, _path(ticker, root))
    return sorted(changed)


def session_over(latest: str, now_ny: datetime) -> bool:
    """The site's latest session is over (after-hours ended): every request sees the same tape."""
    return now_ny >= datetime.combine(datetime.fromisoformat(latest).date(), AFTER_HOURS_END, NY)


def singles(ranges: Dict[int, Levels], sessions: List[str]) -> Tuple[Dict[str, Levels], Dict[str, str]]:
    """Single sessions from cumulative windows: ranges[k] = latest k + 1 sessions; sessions = oldest .. latest.
    Returns ({date: levels}, {date: why not}) - a day is skipped when a window is missing or a difference is < 0."""
    out: Dict[str, Levels] = {}
    bad: Dict[str, str] = {}
    for k in sorted(ranges):
        if k >= len(sessions):
            break
        d = sessions[-1 - k]
        if k == 0:
            out[d] = {p: list(v) for p, v in ranges[0].items()}
            continue
        if k - 1 not in ranges:
            bad[d] = f"day_range {k - 1} missing"
            continue
        cur, prev = ranges[k], ranges[k - 1]
        lv: Levels = {}
        neg = []
        for p in set(cur) | set(prev):
            a, b = cur.get(p, [0.0, 0.0]), prev.get(p, [0.0, 0.0])
            v = [a[0] - b[0], a[1] - b[1]]
            if v[0] < 0 or v[1] < 0:
                neg.append(p)
            if v[0] or v[1]:
                lv[p] = v
        if neg:
            bad[d] = f"negative difference at {len(neg)} buckets (the windows saw different tapes)"
            continue
        out[d] = lv
    return out, bad
