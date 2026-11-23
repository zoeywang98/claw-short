"""@ZZ in the claw-short channel when the UW site (DICloak) and the UW API disagree on dark pool price levels.

ZZ 2026-11-22: "如果有不一致的，@我提醒". Two callers:
- pipeline.main after each fetch run, with every ticker's darkpool-levels source_check (layers._end_day_levels:
  windows ending on the site's latest session; layers.layer_darkpool_levels: earlier single days from the saved
  site history). `fetch.py --no-alert` turns it off.
- site_capture.py (nightly save of the site's tables) for each saved session that differs from the API's.
Rules:
- Only real disagreements: both sources answered and the tables still differ (after the paired retries on a live
  day). DICloak being unavailable, or the site's latest session not being the day, is not alerted (run_log only).
- One message per run, listing every new mismatch. Each (data date, ticker, window or day, 盘中 / 盘后) is alerted
  once; the state is in .dp_source_alerts.json (last 14 days kept).
- Best effort: a failed post is reported back to the caller and never fails the fetch; it is retried next run.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

CHANNEL = "channel:1553568018200657973"   # #claw-short, where the scan posts (daily_short/analyze.py)
ACCOUNT = "default"
NOTIFY = "<@862859550104223764>"          # ZZ
STATE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".dp_source_alerts.json")
OPENCLAW_FALLBACK = "/Users/yuwang/.nvm/versions/node/v24.16.0/bin/openclaw"
KEEP_DAYS = 14


def _md(d: str) -> str:
    return d[5:].replace("-", "/")


def item(ticker: str, label: str, data_date: str, compare: Dict[str, Any], attempts: int = 1,
         live: bool = False) -> Dict[str, Any]:
    """One mismatch. label = window (1D / 2D / 3D / 1W / 1M, ending on data_date) or "day" (one past session)."""
    dt, ct = compare.get("dark_total") or {}, compare.get("centroid_top8") or {}
    return {"ticker": ticker, "label": label, "date": data_date, "attempts": attempts, "live": live,
            "buckets_differ": compare.get("buckets_differ"), "buckets": compare.get("buckets"),
            "one_sided": compare.get("one_sided"),
            "dark_pct": (dt["dicloak"] / dt["api"] - 1) * 100 if dt.get("api") else None,
            "centroid_dicloak": ct.get("dicloak"), "centroid_api": ct.get("api")}


def mismatches(ticker: str, check: Optional[Dict[str, Any]], live: bool = False) -> List[Dict[str, Any]]:
    """The mismatches in one ticker's darkpool-levels source_check."""
    if not check:
        return []
    out = []
    for lab, w in (check.get("windows") or {}).items():
        if w.get("match") is False and "compare" in w:
            out.append(item(ticker, lab, check["date"], w["compare"], check.get("attempts") or 1, live))
    for d, x in sorted((check.get("days") or {}).items()):
        if x.get("match") is False and "compare" in x:
            out.append(item(ticker, "day", d, x["compare"]))
    return out


def _num(x: Optional[float]) -> str:
    return "?" if x is None else f"{x:,.2f}"


def _what(it: Dict[str, Any]) -> str:
    if it["label"] == "day":
        return f"{_md(it['date'])} 单日"
    if it["label"] == "1D":
        return f"当天（{_md(it['date'])}）"
    return f"{it['label']}（截至 {_md(it['date'])}）"


def message(items: List[Dict[str, Any]], when: str) -> str:
    lines = [f"{NOTIFY} 暗池价位 DICloak 和 API 不一致（{when} 取数），下面这些用了 API 的数："]
    for it in items:
        p = it["dark_pct"]
        pct = ("差多少不清楚" if p is None else "一样" if abs(p) < 0.005
               else f"多 {p:.2f}%" if p > 0 else f"少 {-p:.2f}%")
        kind = "像是两边取数的时间差（一边比另一边新）" if it["one_sided"] else "两边各有多有少，不像时间差"
        tries = f"成对重取 {it['attempts']} 次后，" if it["attempts"] > 1 else ""
        lines.append(f"- {it['ticker']} {_what(it)}：{tries}{it['buckets_differ']}/{it['buckets']} 档不同，"
                     f"DICloak 暗池量比 API {pct}，重心 DICloak {_num(it['centroid_dicloak'])}、"
                     f"API {_num(it['centroid_api'])}；{kind}")
    return "\n".join(lines)


def _load(path: str) -> Dict[str, Any]:
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _save(path: str, state: Dict[str, Any], today: str) -> None:
    cut = (date.fromisoformat(today) - timedelta(days=KEEP_DAYS)).isoformat()
    state = {d: v for d, v in state.items() if d >= cut}
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(state, fh, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


def send(text: str) -> None:
    exe = shutil.which("openclaw") or OPENCLAW_FALLBACK
    subprocess.run([exe, "message", "send", "--channel", "discord", "--account", ACCOUNT, "--target", CHANNEL,
                    "--message", text], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=120)


def phase_of(data_date: str, now_ny: datetime) -> str:
    return "盘中" if (data_date == now_ny.date().isoformat() and (now_ny.hour, now_ny.minute) < (16, 0)) else "盘后"


def notify_items(items: List[Dict[str, Any]], now_ny: datetime, state_file: str = STATE,
                 sender: Callable[[str], None] = send) -> Optional[str]:
    """Post one alert for the items not alerted before. Returns a run_log note, or None when nothing was new."""
    state = _load(state_file)
    new = []
    for it in items:
        key = f"{it['ticker']}|{it['label']}|{phase_of(it['date'], now_ny) if it['live'] else '盘后'}"
        if key not in state.get(it["date"], {}):
            new.append((it, key))
    if not new:
        return None
    what = ", ".join(f"{it['ticker']} {it['label'] if it['label'] != 'day' else it['date']}" for it, _ in new)
    try:
        sender(message([it for it, _ in new], f"{now_ny:%m/%d %H:%M}"))
    except (OSError, subprocess.SubprocessError) as e:
        err = getattr(e, "stderr", None) or ""
        return f"DICloak != API ({what}); the @ZZ alert failed: {type(e).__name__} {str(err)[-200:]}".strip()
    for it, key in new:
        state.setdefault(it["date"], {})[key] = f"{now_ny:%Y-%m-%d %H:%M}"
    _save(state_file, state, now_ny.date().isoformat())
    return f"DICloak != API ({what}): alerted @ZZ in #claw-short"


def notify(checks: Dict[str, Optional[Dict[str, Any]]], D: str, now_ny: datetime, state_file: str = STATE,
           sender: Callable[[str], None] = send) -> Optional[str]:
    """pipeline.main: {ticker: source_check} of one fetch run (target date D)."""
    live = D == now_ny.date().isoformat()
    items = [it for T, chk in checks.items() for it in mismatches(T, chk, live=live)]
    return notify_items(items, now_ny, state_file, sender) if items else None
