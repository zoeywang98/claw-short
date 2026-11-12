#!/usr/bin/env python3
"""Dark-pool zone watch (Olivia 2026-11-11: "Visa 425-430 new dp appears but price doesn't go up" / "vrt 190-202
increase new dp but price doesn't drop" / "两小时统计一次就可以"; ZZ 2026-11-11: "一直盯着").

Every run (cron every 5 min) before 16:00 ET reads, for each active zone in dpzone/zones.json, today's dark volume
inside [lo, hi] (UW /api/darkpool/<T>/price-levels, every print, by price bucket) and the RTH 5m bars, and decides:

  kind "dist"  (派发观察区): day zone volume >= min_shares, the session high is >= 30 min old, price <= hi
               -> "符合：放量但涨不上去"
  kind "accum" (吸筹观察区): the mirror on the session low, price >= lo -> "符合：放量但跌不下去"

  - at 11:30 / 13:30 / 15:30: one tally post for all zones (volume since the previous tally and for the day, session
    high / low, price, the verdict); a slot missed by the scheduler is still done within 30 min;
  - between tallies: the first time a zone turns 符合 that day, an immediate alert (one per zone per day; a tally that
    already shows 符合 counts as that alert).
A zone runs from `start` until `until` (no `until` = until someone takes it out). Optional stop_above / stop_below:
the first run at/after 16:00 ends the zone on a close past them. State: dpzone/state_<D>.json; ended zones:
dpzone/ended.json; log: dpzone/log_<D>.txt.

usage: dpzone.py [--dry-run] [--force]   (--force: tally now, whatever the time; with --dry-run for a manual look)
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, time as dtime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(WS, "uw_short_fetch"))
import analyze  # noqa: E402
from uwsf import layers as L  # noqa: E402
from uwsf.client import UWClient, load_token  # noqa: E402

DIR = os.path.join(HERE, "dpzone")
OPEN, BELL, LAST = dtime(9, 30), dtime(16, 0), dtime(16, 10)
SLOTS = (dtime(11, 30), dtime(13, 30), dtime(15, 30))
GRACE = timedelta(minutes=30)   # a slot missed by the scheduler is still done by a run this soon after it
STALL = timedelta(minutes=30)
NAME = {"dist": ("派发观察区", "高", "涨不上去"), "accum": ("吸筹观察区", "低", "跌不下去")}


def rows(body):
    return (body.get("data", []) if isinstance(body, dict) else body) or []


def load(p, default):
    try:
        return json.load(open(p))
    except (OSError, ValueError):
        return default


def wan(n):
    return f"{n / 1e4:.1f} 万股" if n >= 1e4 else f"{n:,} 股"


def rth_bars(c, T, D):
    out = []
    for r in rows(c.get(f"/api/stock/{T}/ohlc/5m", {"date": D}).body):
        t = datetime.fromisoformat(r["start_time"].replace("Z", "+00:00")).astimezone(L.NY)
        if t.date().isoformat() == D and OPEN <= t.time() < BELL:
            out.append((t, float(r["high"]), float(r["low"]), float(r["close"])))
    return sorted(out)


def snap(c, D, now, z):
    """Zone volume, session extreme and verdict for one zone right now."""
    T, lo, hi, kind = z["ticker"], z["lo"], z["hi"], z["kind"]
    ext, verdict = NAME[kind][1], NAME[kind][2]
    lv = rows(c.get(f"/api/darkpool/{T}/price-levels", {"date": D}).body)
    x = {"vol": int(sum(float(r["dark_pool_volume"]) for r in lv if lo <= float(r["price"]) <= hi)),
         "day": int(sum(float(r["dark_pool_volume"]) for r in lv)), "bars": False, "ok": False}
    bars = rth_bars(c, T, D)
    if not bars:
        return x
    t_ext, px_ext = (max(bars, key=lambda b: b[1])[:2] if kind == "dist"
                     else (lambda b: (b[0], b[2]))(min(bars, key=lambda b: b[2])))
    last = bars[-1][3]
    if kind == "dist" and last > hi:
        why = f"已站上 {hi:g}"
    elif kind == "accum" and last < lo:
        why = f"已跌破 {lo:g}"
    elif x["vol"] < z["min_shares"]:
        why = "量还不够"
    elif now - (t_ext + timedelta(minutes=5)) < STALL:   # the extreme bar's end, to be conservative
        why = f"最近 30 分钟还在创新{ext}"
    else:
        why = f"符合：放量但{verdict}"
    x.update(bars=True, last=last, t_ext=t_ext, px_ext=px_ext, why=why, ok=why.startswith("符合"))
    return x


def main(argv=None):
    ap = argparse.ArgumentParser(prog="dpzone.py")
    ap.add_argument("--dry-run", action="store_true", help="print, do not post or record")
    ap.add_argument("--force", action="store_true", help="tally now, whatever the time")
    a = ap.parse_args(argv)

    now = datetime.now(L.NY)
    D = now.date().isoformat()
    if not a.force and (now.weekday() >= 5 or not OPEN <= now.time() <= LAST):
        print(f"NO_REPLY outside regular hours ({now:%a %H:%M} ET)")
        return 0
    ended_p, state_p = os.path.join(DIR, "ended.json"), os.path.join(DIR, f"state_{D}.json")
    ended, s = set(load(ended_p, [])), load(state_p, {})
    zones = []
    for z in load(os.path.join(DIR, "zones.json"), []):
        zid = f"{z['ticker']}|{z['lo']:g}-{z['hi']:g}|{z['kind']}"
        if z["start"] <= D <= (z.get("until") or "9999-12-31") and zid not in ended:
            zones.append((zid, z))
    if not zones:
        print("NO_REPLY no active zones")
        return 0

    done, alerted = s.setdefault("done", []), s.setdefault("alerted", [])
    due = [x for x in SLOTS if x <= now.time() and now - datetime.combine(now.date(), x, L.NY) < GRACE
           and f"{x:%H:%M}" not in done]
    close_due = (now.time() >= BELL and not s.get("close_checked")
                 and any(z.get("stop_above") or z.get("stop_below") for _, z in zones))
    if not (a.force or now.time() < BELL or close_due):
        print(f"NO_REPLY after the bell ({now:%H:%M})")
        return 0

    c = UWClient(load_token())
    lines, log, undo = [], [], []
    old = {"done": list(done), "alerted": list(alerted), "tallies": dict(s.get("tallies", {}))}
    undo.append(lambda: (done.clear(), done.extend(old["done"]), alerted.clear(), alerted.extend(old["alerted"]),
                         s.update(tallies=old["tallies"])))
    if a.force or now.time() < BELL:
        snaps = {zid: snap(c, D, now, z) for zid, z in zones}
        for zid, z in zones:
            x = snaps[zid]
            log.append(f"{z['ticker']} {x['vol']}/{x['day']}" + (f" px {x['last']:.2f} {x['why']}" if x["bars"] else " no bars"))
        if a.force or due:   # tally post; a 符合 shown here counts as that zone's alert for the day
            slot = f"{due[-1]:%H:%M}" if due else f"{now:%H:%M}"
            prev_slot, tallies = (done[-1] if done else None), s.setdefault("tallies", {})
            lines.append(f"**暗池区间统计** · {slot} ET")
            for zid, z in zones:
                x, prev = snaps[zid], tallies.get(zid)
                tallies[zid] = x["vol"]
                ext = NAME[z["kind"]][1]
                since = f"{prev_slot} 以来" if prev is not None else "开盘以来（含盘前）"
                text = (f"{z.get('name', z['ticker'])} {z['lo']:g}–{z['hi']:g}：{since}新增暗池 "
                        f"{wan(max(x['vol'] - (prev or 0), 0))}，今天累计 {wan(x['vol'])} / 门槛 {z['min_shares'] / 1e4:g} 万")
                if x["bars"]:
                    text += f" · 今天最{ext} {x['px_ext']:.2f}（{x['t_ext']:%H:%M}）· 现价 {x['last']:.2f} → {x['why']}"
                    if x["ok"] and zid not in alerted:
                        alerted.append(zid)
                else:
                    text += " · 没有今天的 5 分钟线"
                lines.append(text)
            lines.append(f"（{zones[0][1].get('by', '')} 设，每天 {' / '.join(f'{t:%H:%M}' for t in SLOTS)} 统计；"
                         "中间符合条件会单独提醒，每个区间一天一次）")
            done.append(slot)
        else:                 # between tallies: alert the first time a zone turns 符合 today
            for zid, z in zones:
                x = snaps[zid]
                if x["ok"] and zid not in alerted:
                    alerted.append(zid)
                    ext = NAME[z["kind"]][1]
                    lines.append(f"**{z.get('name', z['ticker'])} 暗池提醒** · {now:%H:%M} ET\n"
                                 f"{z['lo']:g}–{z['hi']:g} 今天暗池成交 {wan(x['vol'])}（门槛 {z['min_shares'] / 1e4:g} 万），"
                                 f"今天最{ext} {x['px_ext']:.2f}（{x['t_ext']:%H:%M}）以后没再创新{ext}，"
                                 f"现价 {x['last']:.2f} → {x['why']}")
    if close_due and not a.force:
        s["close_checked"] = True
        undo.append(lambda: s.update(close_checked=False))
        for zid, z in zones:
            if not (z.get("stop_above") or z.get("stop_below")):
                continue
            bars = rth_bars(c, z["ticker"], D)
            if not bars:
                continue
            last = bars[-1][3]
            why = (f"站上 {z['stop_above']:g}" if z.get("stop_above") and last > z["stop_above"] else
                   f"跌破 {z['stop_below']:g}" if z.get("stop_below") and last < z["stop_below"] else "")
            log.append(f"{z['ticker']} close {last:.2f}{' ended' if why else ''}")
            if why:
                ended.add(zid)
                undo.append(lambda zid=zid: ended.discard(zid))
                lines.append(f"**{z.get('name', z['ticker'])} 暗池观察区结束** · {now:%m-%d} 收盘 {last:.2f} {why}，"
                             f"{z['lo']:g}–{z['hi']:g} {NAME[z['kind']][0]}不再盯")

    line = f"{now:%H:%M} " + " · ".join(log)
    if lines:
        text = "\n".join(lines)
        print(text)
        if not a.dry_run:
            try:
                analyze.post(text)
            except subprocess.CalledProcessError as e:   # undo so the next run retries
                print(f"⚠ post failed, will retry next run: {e}", file=sys.stderr)
                for u in undo:
                    u()
                line += " (post failed)"
            except subprocess.TimeoutExpired:
                line += " (send timed out, usually delivered)"
    else:
        print(f"NO_REPLY {line}")
    if not a.dry_run:
        os.makedirs(DIR, exist_ok=True)
        json.dump(s, open(state_p, "w"), ensure_ascii=False, indent=1)
        json.dump(sorted(ended), open(ended_p, "w"), ensure_ascii=False)
        with open(os.path.join(DIR, f"log_{D}.txt"), "a") as fh:
            fh.write(line + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
