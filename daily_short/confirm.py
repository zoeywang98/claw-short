#!/usr/bin/env python3
"""Pre-open confirmation (SHORT_ENGINE §6 / §8.1): the 17:00 scan can never see the next-day OI for that day's
flow, so every name from the last scan (whatever its tier) is re-read once today's OI is published, with the
pre-market tape and the latest borrow. Inputs go to analysis_data/<D>_premarket/<T>.json, replies to logs/<D>_premarket/.

usage: confirm.py [--scan-date L] [--date D] [--tickers A,B] [--asof HH:MM] [--wait-minutes 30] [--dry-run]
  --scan-date  scan whose names are confirmed (default: the latest logs/<date> before D)
  --tickers    only these names (default: every name in the scan)
  --date       confirmation day (default: today, New York)
  --asof       cutoff for pre-market bars / borrow (default: now); for replays such as --date 2026-09-28 --asof 09:00
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time as dtime

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(WS, "uw_short_fetch"))
import analyze  # noqa: E402
from uwsf import layers as L  # noqa: E402
from uwsf.client import UWClient, load_token  # noqa: E402

TOP_N = 30


def verdict(text):
    m = re.search(r"\*\*结论\*\*[:：]\s*(.*)", text or "")
    return m.group(1).strip() if m else ""


def scan_names(L_date, only):
    log = os.path.join(HERE, "logs", L_date)
    out = []
    for f in sorted(os.listdir(log)):
        if not f.endswith(".reply.json") or f.startswith("_"):
            continue
        t = f[:-len(".reply.json")]
        if only and t not in only:
            continue
        r = json.load(open(os.path.join(log, f)))
        out.append((t, verdict(r.get("result")), r.get("result")))
    return out


def latest_scan_before(D):
    days = [d for d in os.listdir(os.path.join(HERE, "logs")) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) and d < D]
    return max(days) if days else None


def pick_oi_rows(oc, brief):
    """Totals, the largest changes, and every row at the gex wall / flip strikes or on last night's top flow contracts."""
    gex = brief.get("gex_levels") or {}
    levels = [v for k in ("latest", "latest_oi") for kk, v in (gex.get(k) or {}).items()
              if kk in ("call_wall", "put_wall", "gamma_flip", "gamma_magnet") and isinstance(v, (int, float))]
    flow_syms = {c.get("sym") for c in ((brief.get("option_trades") or {}).get("aggregates") or {}).get("top_contracts") or []}
    strikes = sorted({c["strike"] for c in oc["contracts"] if c.get("strike") is not None})
    near = set()
    for lv in levels:  # the listed strike at or just around each level
        below = [k for k in strikes if k <= lv][-2:]
        above = [k for k in strikes if k > lv][:2]
        near.update(below + above)
    rows = [c for c in oc["contracts"] if c.get("oi_diff") and (c.get("strike") in near or c.get("sym") in flow_syms)]
    return {"totals": oc["totals"], "top_increase": oc["top_increase"][:TOP_N], "top_decrease": oc["top_decrease"][:TOP_N],
            "at_levels_and_flow_contracts": sorted(rows, key=lambda c: (c["strike"], c["type"], c["expiry"])),
            "levels_used": sorted(set(levels)), "note": oc.get("note")}


def compact_structure(brief):
    ot = (brief.get("option_trades") or {}).get("aggregates") or {}
    dl = (brief.get("darkpool_levels") or {}).get("windows") or {}
    return {
        "gex_levels": brief.get("gex_levels"),
        "option_trades": {k: ot.get(k) for k in ("premium_by_type_side", "net_call_premium", "net_put_premium",
                                                 "sweep_count", "flow_iv", "top_contracts")},
        "price": (brief.get("price") or {}).get("derived"),
        "darkpool_windows": {k: {kk: v.get(kk) for kk in ("from", "to", "poc", "centroid_top8", "dp_pct")} for k, v in dl.items()},
        "greek_exposure_series": (brief.get("greek_exposure") or {}).get("series_21d"),
    }


def premarket(m5, prev_close):
    if not (m5 and m5.ok):
        return {"status": "missing", "reason": m5.reason if m5 else "not fetched"}
    D = max(m5.data["days"])
    bars = m5.data["days"][D]
    pre = [b for b in bars if b[6] == "pr"]
    rth = [b for b in bars if b[6] == "r"]
    last = (pre or bars)[-1][4] if (pre or bars) else None
    out = {"date": D, "through": bars[-1][0] if bars else None, "prev_close": prev_close,
           "premarket_volume": sum(b[5] or 0 for b in pre),
           "premarket_high": max((b[2] for b in pre if b[2] is not None), default=None),
           "premarket_low": min((b[3] for b in pre if b[3] is not None), default=None),
           "last": last, "last_vs_prev_close": (last / prev_close - 1) if (last and prev_close) else None,
           "rth_started": bool(rth), "bars_5m": pre[-24:] + rth[:6]}
    return out


def fetch_confirmation(client, cal, T, D, cutoff, raw_root):
    cfg = L.Config()
    ctx = L.Ctx(client, T, D, cal, cfg, raw_root, os.path.join(WS, "uw_short_fetch", "cache"),
                datetime.now(L.NY).date().isoformat(), cutoff)
    ctx.K = D  # OI / greek exposure for D are known before the open; nothing here reads end-of-day sources
    res = {name: L.run_layer(name, core, fn, ctx) for name, core, fn in (
        ("oi-change", False, L.layer_oi_change), ("short-data", True, L.layer_short_data),
        ("ohlc-5m", False, L.layer_ohlc_5m), ("greek-exposure", True, L.layer_greek_exposure))}
    return res


def oi_ready(res, D):
    oc = res["oi-change"]
    return oc.ok and {c.get("curr_date") for c in oc.data["contracts"]} == {D}


def claude(system, user):
    cmd = ["claude", "-p", "--model", analyze.MODEL, "--effort", analyze.EFFORT, "--system-prompt", system,
           "--tools", "", "--strict-mcp-config", "--setting-sources", "", "--no-session-persistence", "--output-format", "json"]
    sandbox = os.path.join(HERE, "sandbox")
    os.makedirs(sandbox, exist_ok=True)
    p = subprocess.run(cmd, input=user, capture_output=True, text=True, cwd=sandbox, timeout=analyze.TIMEOUT_S)
    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError:
        return {"is_error": True, "result": (p.stdout or p.stderr)[-2000:]}


def post(text):
    """Like analyze.post, but a send that hangs past the timeout usually still arrives, so keep going with the
    next chunk instead of dropping the rest; a hard failure is retried once."""
    problems = []
    for i, part in enumerate(analyze.chunks(text)):
        for attempt in (1, 2):
            try:
                subprocess.run(["openclaw", "message", "send", "--channel", "discord", "--account", analyze.ACCOUNT,
                                "--target", analyze.CHANNEL, "--message", part], check=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=150)
                break
            except subprocess.TimeoutExpired:
                problems.append(f"chunk {i + 1}: send timed out (usually delivered anyway)")
                break
            except subprocess.CalledProcessError as e:
                if attempt == 2:
                    problems.append(f"chunk {i + 1}: send failed: {(e.stderr or b'')[-200:]!r}")
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(prog="confirm.py")
    ap.add_argument("--scan-date")
    ap.add_argument("--date")
    ap.add_argument("--tickers", default="")
    ap.add_argument("--asof", help="HH:MM New York cutoff for replays (default: now)")
    ap.add_argument("--wait-minutes", type=int, default=30, help="keep retrying until the day's OI is published")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    now = datetime.now(L.NY)
    D = a.date or now.date().isoformat()
    if date.fromisoformat(D).weekday() >= 5:
        print(f"NO_REPLY {D} is a weekend")
        return 0
    L_date = a.scan_date or latest_scan_before(D)
    if not L_date:
        print(f"NO_REPLY no scan before {D}")
        return 0
    only = {t for t in a.tickers.split(",") if t}
    names = scan_names(L_date, only)
    if not names:
        print(f"NO_REPLY no names in the {L_date} scan")
        return 0
    cutoff = datetime.combine(date.fromisoformat(D), dtime(*map(int, a.asof.split(":"))), L.NY) if a.asof else now

    client = UWClient(load_token())
    cal_days = L.Calendar.from_ohlc(client.get("/api/stock/SPY/ohlc/1d", {"timeframe": "1Y"}).body).days
    cal = L.Calendar(cal_days + [D])
    raw_root = os.path.join(WS, "uw_short_fetch", "runs", "premarket", D)
    an_dir = os.path.join(WS, "analysis_data", f"{D}_premarket")
    log_dir = os.path.join(HERE, "logs", f"{D}_premarket")
    os.makedirs(an_dir, exist_ok=True)
    os.makedirs(log_dir, exist_ok=True)

    deadline = time.time() + 60 * a.wait_minutes
    while True:  # the day's OI is the whole point: wait for it (a market holiday never publishes it)
        probe = fetch_confirmation(client, cal, names[0][0], D, cutoff, raw_root)
        if oi_ready(probe, D) or time.time() > deadline:
            break
        time.sleep(300)
    if not oi_ready(probe, D):
        print(f"NO_REPLY OI for {D} not published by {datetime.now(L.NY):%H:%M} ET (holiday or late) · {probe['oi-change'].log_line()}")
        return 0

    system = "\n\n".join([open(os.path.join(HERE, "CONFIRM.md")).read(),
                          "## SHORT_ENGINE.md\n\n" + open(os.path.join(WS, "SHORT_ENGINE.md")).read()])

    def one(item):
        T, v, reply = item
        res = probe if T == names[0][0] else fetch_confirmation(client, cal, T, D, cutoff, raw_root)
        while not oi_ready(res, D) and time.time() < deadline:  # OI is rolled out contract by contract, not all at once
            time.sleep(60)
            res = fetch_confirmation(client, cal, T, D, cutoff, raw_root)
        brief_p = os.path.join(WS, "analysis_data", L_date, f"{T}.json")
        brief = json.load(open(brief_p)) if os.path.exists(brief_p) else {}
        prev_close = ((brief.get("price") or {}).get("derived") or {}).get("close")
        data = {
            "ticker": T, "scan_date": L_date, "confirm_date": D, "cutoff": cutoff.isoformat(timespec="minutes"),
            "last_night_verdict": v, "last_night_reply": reply,
            "last_night_structure": compact_structure(brief),
            "next_day_oi": pick_oi_rows(res["oi-change"].data, brief) if res["oi-change"].ok else {"status": "missing", "reason": res["oi-change"].reason},
            "premarket": premarket(res["ohlc-5m"], prev_close),
            "borrow": res["short-data"].data.get("latest") if res["short-data"].ok else {"status": "missing", "reason": res["short-data"].reason},
            "greek_exposure_today": res["greek-exposure"].data.get("today") if res["greek-exposure"].ok else {"status": "missing", "reason": res["greek-exposure"].reason},
            "run_log": [r.log_line() for r in res.values()],
        }
        with open(os.path.join(an_dir, f"{T}.json"), "w") as f:
            json.dump(L_round(data), f, ensure_ascii=False, separators=(",", ":"))
        r = claude(system, json.dumps(L_round(data), ensure_ascii=False))
        with open(os.path.join(log_dir, f"{T}.reply.json"), "w") as f:
            json.dump(r, f, ensure_ascii=False, indent=1)
        return T, v, r

    with ThreadPoolExecutor(max_workers=4) as ex:
        results = list(ex.map(one, names))

    lines, problems = [], []
    for T, v, r in results:
        new = verdict(r.get("result")) if not r.get("is_error") else f"昨晚 {v[:12]} → ❌ 确认失败"
        lines.append(f"{T}：{new[:60]}")
    header = (f"**盘前确认 · {D}**（{L_date} 收盘扫描的 {len(results)} 只，用今早公布的次日 OI 补齐 §6）\n" + "\n".join(lines))
    print(header)
    if not a.dry_run:
        problems += post(header)
        for T, v, r in results:
            if not r.get("is_error") and r.get("result"):
                problems += [f"{T} {p}" for p in post(r["result"])]
    if problems:
        print("\n".join(problems), file=sys.stderr)
    return 0 if all(not r.get("is_error") for _, _, r in results) else 1


def L_round(o):
    if isinstance(o, float):
        return float(f"{o:.6g}")
    if isinstance(o, dict):
        return {k: L_round(v) for k, v in o.items()}
    if isinstance(o, list):
        return [L_round(v) for v in o]
    return o


if __name__ == "__main__":
    sys.exit(main())
