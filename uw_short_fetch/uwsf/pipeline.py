"""CLI, orchestration, snapshot files and the per-layer run log (SHORT_ENGINE.md §8)."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time as dtime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from . import __version__
from . import layers as L
from . import watchlist as W
from .client import UWClient, load_token
from .layers import CORE_LAYERS, NY, Calendar, Config, Ctx, LayerResult, run_layer, rows_of

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PHASE_A = [
    ("darkpool-levels", True, L.layer_darkpool_levels),
    ("darkpool", True, L.layer_darkpool),
    ("option-trades", True, L.layer_option_trades),
    ("gex-levels", True, L.layer_gex_levels),
    ("greek-exposure", True, L.layer_greek_exposure),
    ("short-interest", True, L.layer_short_interest),
    ("short-volume", True, L.layer_short_volume),
    ("short-data", True, L.layer_short_data),
    ("lit-blocks", False, L.layer_lit_blocks),
    ("ohlc-daily", False, L.layer_ohlc_daily),
    ("ohlc-5m", False, L.layer_ohlc_5m),
    ("oi-change", False, L.layer_oi_change),
    ("option-contracts", False, L.layer_option_contracts),
    ("oi-per-strike", False, L.layer_oi_per_strike),
    ("options-volume", False, L.layer_options_volume),
    ("interpolated-iv", False, L.layer_interpolated_iv),
    ("option-sentiment", False, L.layer_option_sentiment),
    ("unusualness", False, L.layer_unusualness),
    ("options-pulse", False, L.layer_options_pulse),
    ("multi-leg", False, L.layer_multi_leg),
    ("flow-per-strike", False, L.layer_flow_per_strike),
    ("net-prem-ticks", False, L.layer_net_prem_ticks),
    ("greek-exposure-strike", False, L.layer_greek_exposure_strike),
    ("offlit-levels", False, L.layer_offlit_levels),
    ("flow-alerts", False, L.layer_flow_alerts),
    ("spot-gex", False, L.layer_spot_gex),
]
PHASE_B = ["contract-history", "rr-skew"]
SCREENER = "/api/screener/stocks"


# --------------------------------------------------------------------------- args
def parse_args(argv: Optional[List[str]]) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="fetch.py", description=(
        "Fetch every Unusual Whales input SHORT_ENGINE.md needs. Data only: no veto, breaker or fingerprint verdicts."))
    ap.add_argument("--tickers", default="", help="comma-separated candidates, e.g. NBIS,AXTI (default: the built-in watchlist)")
    ap.add_argument("--tickers-file", help="file with candidates (comma / whitespace / newline separated, # comments)")
    ap.add_argument("--group", default="", help="watchlist groups to run when no tickers are given: "
                    + ", ".join(f"{k} ({v['label']})" for k, v in W.WATCHLIST.items()))
    ap.add_argument("--date", help="target trading date YYYY-MM-DD (default: latest trading day)")
    ap.add_argument("--asof", help="point-in-time cutoff HH:MM (New York time) on --date; drops data after it "
                                   "and uses the prior session for end-of-day-only sources")
    ap.add_argument("--universe-file", help="circuit-breaker names (default: top --universe-size by market cap in each candidate's sector)")
    ap.add_argument("--universe-size", type=int, default=35)
    ap.add_argument("--out", default=os.path.join(PROJECT_DIR, "data"))
    ap.add_argument("--cache", default=os.path.join(PROJECT_DIR, "cache"))
    ap.add_argument("--env-file", default="~/.openclaw/.env")
    ap.add_argument("--token-env", default="UW_API_TOKEN")
    ap.add_argument("--concurrency", type=int, default=4, help="max simultaneous HTTP requests")
    ap.add_argument("--block-shares", type=int, default=10_000, help="block print: size >= this ...")
    ap.add_argument("--block-premium", type=float, default=200_000, help="... or premium >= this (USD)")
    ap.add_argument("--flow-min-premium", type=float, default=50_000, help="option-trades tape filter (USD)")
    ap.add_argument("--multileg-min-size", type=int, default=50, help="multi-leg filter (contracts across legs)")
    ap.add_argument("--dp-days", type=int, default=22)
    ap.add_argument("--gex-days", type=int, default=6)
    ap.add_argument("--flow-days", type=int, default=5)
    ap.add_argument("--skip", default="", help="comma-separated layer names to skip (logged as FAIL)")
    ap.add_argument("--no-cache", action="store_true", help="refetch past dates instead of using cache/")
    ap.add_argument("--quiet", action="store_true")
    return ap.parse_args(argv)


def read_names(text: str) -> List[str]:
    out: List[str] = []
    for line in text.splitlines():
        for tok in re.split(r"[,\s]+", line.split("#", 1)[0]):
            t = tok.strip().upper()
            if t and t not in out:
                out.append(t)
    return out


# --------------------------------------------------------------------------- market level
def fetch_screener_batch(ctx: Ctx, tickers: List[str]) -> LayerResult:
    # end-of-day snapshot: point-in-time uses the prior session K
    rows = rows_of(ctx.get(f"screener_candidates_{ctx.K}", SCREENER, {"ticker": ",".join(tickers), "date": ctx.K, "limit": 500}))
    by_t = {r.get("ticker"): L.screener_subset(r) for r in rows if r.get("ticker")}
    if not by_t:
        return L.FAIL("empty payload")
    missing = [t for t in tickers if t not in by_t]
    dates = sorted({v.get("date") for v in by_t.values() if v.get("date")})
    return LayerResult(ok=True, as_of=dates[-1] if dates else None, rows=len(by_t), data=by_t,
                       notes=([f"missing from screener: {', '.join(missing)}"] if missing else [])
                       + L.pit_note(ctx, f"screener rows are end-of-day snapshots; using {ctx.K}"))


def fetch_universes(ctx: Ctx, universe_file: Optional[str], sectors: List[str]) -> List[LayerResult]:
    """Circuit-breaker pool. Gamma is read for D (UW computes daily gamma from OI at the open);
    in point-in-time mode the top-N membership comes from the prior session's market caps."""
    specs: List[Tuple[str, str, Dict[str, Any], List[str]]] = []
    if universe_file:
        with open(os.path.expanduser(universe_file)) as fh:
            names = read_names(fh.read())
        specs.append((f"file {os.path.basename(universe_file)} ({len(names)} names)", "universe_file",
                      {"ticker": ",".join(names), "date": ctx.D, "limit": 500}, names))
    else:
        for s in sectors:
            params = {"sectors[]": s, "order": "marketcap", "order_direction": "desc",
                      "limit": ctx.cfg.universe_size, "date": ctx.K}
            if ctx.pit:
                members = [r.get("ticker") for r in rows_of(ctx.get(f"universe_members_{s}_{ctx.K}", SCREENER, params)) if r.get("ticker")]
                specs.append((f"{s} · top {ctx.cfg.universe_size} by market cap on {ctx.K}", f"universe_{s}",
                              {"ticker": ",".join(members), "date": ctx.D, "limit": 500}, members))
            else:
                specs.append((f"{s} · top {ctx.cfg.universe_size} by market cap", f"universe_{s}", params, []))
    if not specs:
        return [L.FAIL("no universe: pass --universe-file, or candidates need a screener sector", name="universe")]
    out = []
    for label, raw, params, names in specs:
        def one() -> LayerResult:
            if "ticker" in params and not params["ticker"]:
                return L.FAIL("no universe members")
            rows = rows_of(ctx.get(raw, SCREENER, params))
            if not rows:
                return L.FAIL("empty payload")
            summ = L.universe_summary(label, rows, ctx.D)
            if summ["null"] == summ["n"]:
                return L.FAIL("no gamma values in payload")
            notes = []
            if names:
                got = {i["ticker"] for i in summ["items"]}
                miss = [n for n in names if n not in got]
                if miss:
                    notes.append(f"not returned: {', '.join(miss)}")
            if summ["dates"] != [ctx.D]:
                notes.append(f"row dates {summ['dates']} (expected {ctx.D})")
            return LayerResult(ok=True, as_of=summ["as_of"], rows=summ["n"], data=summ, notes=notes,
                               extra=f"net_gamma<0={summ['negative']}/{summ['n']}")
        out.append(run_layer(f"universe[{label}]", False, one))
    return out


def fetch_correlations(ctx: Ctx, tickers: List[str], sectors: List[str]) -> LayerResult:
    names = list(dict.fromkeys(tickers + [L.SECTOR_ETF[s] for s in sectors if s in L.SECTOR_ETF]))
    if len(names) < 2:
        return L.FAIL("needs at least two tickers")
    end = ctx.K  # daily closes: point-in-time stops at the prior session
    start = (date.fromisoformat(end) - timedelta(days=31)).isoformat()
    rows = rows_of(ctx.get("correlations", "/api/market/correlations",
                           {"tickers": ",".join(names), "start_date": start, "end_date": end}))
    if not rows:
        return L.FAIL("empty payload")
    pairs = [{"a": r.get("fst"), "b": r.get("snd"), "correlation": L.num(r.get("correlation")), "n": L.inum(r.get("rows")),
              "from": r.get("min_date"), "to": r.get("max_date")} for r in rows]
    return LayerResult(ok=True, as_of=max((p["to"] or "") for p in pairs) or end, rows=len(pairs),
                       data={"tickers": names, "window": [start, end], "pairs": pairs})


def fetch_etf_flows(ctx: Ctx, sectors: List[str]) -> LayerResult:
    end = ctx.K
    start = (date.fromisoformat(end) - timedelta(days=45)).isoformat()
    out: Dict[str, Any] = {}
    for s in sectors:
        etf = L.SECTOR_ETF.get(s)
        if not etf:
            continue
        rows = rows_of(ctx.get(f"etf_in_outflow_{etf}", f"/api/etfs/{etf}/in-outflow", {"start_date": start, "end_date": end}))
        rows = sorted((r for r in rows if r.get("date") and r["date"] <= end), key=lambda r: r["date"])[-30:]
        if rows:
            out[etf] = {"sector": s, "series": [{"date": r["date"], "change": L.num(r.get("change")),
                                                 "change_prem": L.num(r.get("change_prem")), "volume": L.inum(r.get("volume")),
                                                 "close": L.num(r.get("close")), "is_fomc": r.get("is_fomc")} for r in rows]}
    if not out:
        return L.FAIL("no sector ETF flow rows" if sectors else "no candidate sectors")
    last = max(v["series"][-1]["date"] for v in out.values())
    return LayerResult(ok=True, as_of=last, rows=sum(len(v["series"]) for v in out.values()),
                       extra=f"etfs={','.join(out)}", data=out)


# --------------------------------------------------------------------------- per ticker
def participation(dp: Optional[LayerResult], lit: Optional[LayerResult]) -> Optional[Dict[str, Any]]:
    if not (dp and dp.ok):
        return None
    dv = dp.data.get("day_volume")
    litb = lit.data["blocks"] if (lit and lit.ok) else None
    out: Dict[str, Any] = {"day_volume": dv, "day_volume_source": "darkpool print `volume` (consolidated day volume at the latest print)",
                           "definition": dp.data.get("block_definition"),
                           "excluded_auction_shares": {"dark": dp.data["blocks"]["auction"]["shares"],
                                                       "lit": litb["auction"]["shares"] if litb else None}}
    for k in ("either", "by_size", "by_premium"):
        dsh = dp.data["blocks"][k]["shares"]
        lsh = litb[k]["shares"] if litb else None
        out[k] = {"dark_block_shares": dsh, "lit_block_shares": lsh,
                  "pct_dark": (dsh / dv) if dv else None,
                  "pct_lit": (lsh / dv) if (dv and lsh is not None) else None,
                  "pct_total": ((dsh + (lsh or 0)) / dv) if dv else None}
    return out


def run_ticker(ctx: Ctx, screener: LayerResult, skip: set) -> Tuple[Dict[str, LayerResult], Dict[str, Any]]:
    res: Dict[str, LayerResult] = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {name: ex.submit(run_layer, name, core, fn, ctx) for name, core, fn in PHASE_A if name not in skip}
        for name, f in futs.items():
            res[name] = f.result()
    if "contract-history" not in skip:
        res["contract-history"] = run_layer("contract-history", False, L.layer_contract_history, ctx, res.get("oi-change"), res.get("gex-levels"))
    if "rr-skew" not in skip:
        res["rr-skew"] = run_layer("rr-skew", False, L.layer_rr_skew, ctx, res.get("oi-change"))
    row = (screener.data or {}).get(ctx.T) if screener.ok else None
    res["screener"] = LayerResult(name="screener", ok=bool(row), as_of=(row or {}).get("date"), rows=1 if row else 0, data=row,
                                  reason=None if row else (screener.reason or "ticker missing from screener batch"))
    for name, core, _ in PHASE_A:
        if name in skip:
            res[name] = LayerResult(name=name, core=core, ok=False, reason="skipped by --skip")
    dp = res.get("darkpool")
    spot = dp.data.get("spot") if (dp and dp.ok) else None
    ges, gex = res.get("greek-exposure-strike"), res.get("gex-levels")
    gex_oi = gex.data.get("latest_oi") if (gex and gex.ok) else None
    derived = {
        "spot": spot,
        "spot_rth_close": dp.data.get("spot_rth_close") if (dp and dp.ok) else None,
        "session_so_far": session_so_far(ctx, res.get("ohlc-5m"), res.get("ohlc-daily")),
        "block_participation": participation(dp, res.get("lit-blocks")),
        "walls_crosscheck": L.oi_basis_walls(ges.data["strikes"], spot["mid"], gex_oi) if (ges and ges.ok and spot) else None,
    }
    return res, derived


def group_gamma(net_gamma: Dict[str, Optional[float]]) -> List[Dict[str, Any]]:
    """Negative-gamma count per watchlist group, from each fetched ticker's greek-exposure row (data only)."""
    out = []
    for slug, g in W.WATCHLIST.items():
        names = [t for t in g["tickers"] if t in net_gamma]  # type: ignore[union-attr]
        if not names:
            continue
        have = {t: net_gamma[t] for t in names if net_gamma[t] is not None}
        neg = [t for t, v in have.items() if v < 0]
        out.append({"group": slug, "label": g["label"], "n": len(have), "negative": len(neg), "negative_names": neg,
                    "missing": [t for t in names if net_gamma[t] is None], "net_gamma": have})
    return out


def session_so_far(ctx: Ctx, m5: Optional[LayerResult], daily: Optional[LayerResult]) -> Optional[Dict[str, Any]]:
    """D's session from 5-minute bars (up to the cutoff in point-in-time mode) vs the previous close."""
    if not (m5 and m5.ok):
        return None
    bars = m5.data["days"].get(ctx.D) or []
    pre = [b for b in bars if b[6] == "pr"]
    rth = [b for b in bars if b[6] == "r"]
    prev_close = None
    if daily and daily.ok:
        closes = [(b[0], b[4]) for b in daily.data["bars"] if b[0] < ctx.D]
        prev_close = closes[-1][1] if closes else None
    last = bars[-1][4] if bars else None
    end = L.parse_ts(bars[-1][0]) + timedelta(minutes=5) if bars else None
    out = {
        "through": end.strftime("%Y-%m-%dT%H:%M:%SZ") if end else None, "prev_close": prev_close,
        "premarket_volume": sum(b[5] or 0 for b in pre),
        "premarket_high": max((b[2] for b in pre if b[2] is not None), default=None),
        "premarket_low": min((b[3] for b in pre if b[3] is not None), default=None),
        "rth_open": rth[0][1] if rth else None,
        "rth_high": max((b[2] for b in rth if b[2] is not None), default=None),
        "rth_low": min((b[3] for b in rth if b[3] is not None), default=None),
        "rth_volume": sum(b[5] or 0 for b in rth),
        "last": last,
    }
    if prev_close:
        out["gap_open_vs_prev_close"] = (out["rth_open"] / prev_close - 1) if out["rth_open"] else None
        out["last_vs_prev_close"] = (last / prev_close - 1) if last else None
    return out


# --------------------------------------------------------------------------- output
def _fmt_pct(x: Optional[float]) -> str:
    return f"{x:.1%}" if isinstance(x, (int, float)) else "n/a"


def ticker_log(T: str, res: Dict[str, LayerResult], derived: Dict[str, Any], pit: bool = False) -> Tuple[List[str], int, int, int]:
    lines = ["", f"== {T} =="]
    core_ok = 0
    for name in CORE_LAYERS:
        r = res[name]
        core_ok += int(r.ok)
        lines.append(r.log_line())
        lines += [f"     note: {n}" for n in r.notes]
    lines.append(f"coverage {core_ok}/{len(CORE_LAYERS)}")
    sup = [r for n, r in res.items() if n not in CORE_LAYERS]
    sup_ok = sum(1 for r in sup if r.ok)
    lines.append("-- supplemental --")
    for r in sup:
        lines.append(r.log_line())
        lines += [f"     note: {n}" for n in r.notes]
    lines.append(f"supplemental {sup_ok}/{len(sup)}")
    spot = derived.get("spot")
    if spot:
        close = derived.get("spot_rth_close")
        lines.append(f"spot {spot['mid']} (DP NBBO mid @ {spot['as_of']})"
                     + (f" · last RTH mid {close['mid']} @ {close['as_of']}" if close else ""))
    ss = derived.get("session_so_far")
    if ss and ss.get("through"):
        lines.append(f"session through {ss['through']}: prev close {ss['prev_close']} · premarket vol {ss['premarket_volume']:,} · "
                     f"RTH open {ss['rth_open']} · last {ss['last']} ({_fmt_pct(ss.get('last_vs_prev_close'))} vs prev close) · "
                     f"RTH vol {ss['rth_volume']:,}")
    bp = derived.get("block_participation")
    if bp:
        e = bp["either"]
        lines.append(f"block participation (≥{bp['definition']['min_shares']:,} sh or ≥${bp['definition']['min_premium']:,.0f}, auctions excluded): "
                     f"dark {_fmt_pct(e['pct_dark'])} + lit {_fmt_pct(e['pct_lit'])} = {_fmt_pct(e['pct_total'])} of day volume {bp['day_volume']:,}"
                     if bp.get("day_volume") else "block participation: day volume unavailable")
    wc = derived.get("walls_crosscheck")
    if wc and pit:
        g = res["gex-levels"].data if res.get("gex-levels") and res["gex-levels"].ok else {}
        lv, lo = g.get("latest") or {}, g.get("latest_oi") or {}
        lines.append(f"walls at cutoff (today's opening OI, spot {wc['spot']}): call {wc['call_wall']} / put {wc['put_wall']} / "
                     f"magnet {wc['gamma_magnet']} · prior-session gex-levels {g.get('levels_date')}: "
                     f"vol call {lv.get('call_wall')} / put {lv.get('put_wall')} / flip {lv.get('gamma_flip')}; "
                     f"oi call {lo.get('call_wall')} / put {lo.get('put_wall')}")
    elif wc and wc.get("vs_gex_levels_oi"):
        diff = [f"{k} {v['gex_levels']} vs {v['strike_table']}" for k, v in wc["vs_gex_levels_oi"].items() if not v["agree"]]
        lines.append("walls cross-check (gex-levels oi vs greek-exposure/strike): " + ("agree" if not diff else "differ: " + "; ".join(diff)))
    return lines, core_ok, sup_ok, len(sup)


def write_json(path: str, obj: Any, indent: Optional[int] = None) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=indent, default=str)
    os.replace(tmp, path)


# --------------------------------------------------------------------------- main
def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    tickers = read_names(args.tickers.replace(",", " "))
    if args.tickers_file:
        with open(os.path.expanduser(args.tickers_file)) as fh:
            tickers += [t for t in read_names(fh.read()) if t not in tickers]
    if not tickers:
        tickers = W.tickers_of(W.resolve_groups(args.group))
    skip = {s.strip() for s in args.skip.split(",") if s.strip()}
    cfg = Config(dp_days=max(22, args.dp_days), gex_days=max(2, args.gex_days), flow_days=max(1, args.flow_days),
                 block_shares=args.block_shares, block_premium=args.block_premium, flow_min_premium=args.flow_min_premium,
                 multileg_min_size=args.multileg_min_size, universe_size=args.universe_size, use_cache=not args.no_cache)
    say = (lambda *a: None) if args.quiet else (lambda *a: print(*a, flush=True))

    client = UWClient(load_token(args.token_env, args.env_file), concurrency=args.concurrency)
    t0 = time.time()
    now_ny = datetime.now(NY)
    today_ny = now_ny.date().isoformat()

    cal_resp = client.get("/api/stock/SPY/ohlc/1d", {"timeframe": "1Y"})
    cal = Calendar.from_ohlc(cal_resp.body)
    D = cal.resolve(args.date) if args.date else cal.latest()
    head_notes = []
    if args.date and D != args.date:
        head_notes.append(f"--date {args.date} is not a trading day; using {D}")
    cutoff = None
    if args.asof:
        m = re.match(r"^(\d{1,2}):(\d{2})$", args.asof.strip())
        if not m:
            print("--asof must be HH:MM (New York time)", file=sys.stderr)
            return 2
        cutoff = datetime.combine(date.fromisoformat(D), dtime(int(m.group(1)), int(m.group(2))), NY)
        if cutoff > now_ny:
            print(f"--asof {cutoff:%Y-%m-%d %H:%M} ET is in the future", file=sys.stderr)
            return 2
    run_id = D + (f"_{cutoff:%H%M}" if cutoff else "")
    out_dir = os.path.join(os.path.expanduser(args.out), run_id)
    cache_dir = os.path.expanduser(args.cache)
    write_json(os.path.join(out_dir, "_market", "raw", "calendar_spy_ohlc_1d.json"), cal_resp.envelope())
    say(f"target {D}" + (f" as of {cutoff:%H:%M} ET" if cutoff else "") + f" (latest trading day {cal.latest()}) · tickers {', '.join(tickers)}")

    mctx = Ctx(client, "_market", D, cal, cfg, out_dir, cache_dir, today_ny, cutoff)
    if cutoff:
        head_notes.append(f"point-in-time as of {cutoff:%Y-%m-%d %H:%M} ET: rows after the cutoff are dropped; "
                          f"end-of-day-only sources use the prior session {mctx.K}; OI and daily greek exposure for {D} "
                          f"are computed at the open and kept")
    screener = run_layer("screener-batch", False, fetch_screener_batch, mctx, tickers)
    sectors = sorted({v.get("sector") for v in (screener.data or {}).values() if v.get("sector")}) if screener.ok else []
    universes = fetch_universes(mctx, args.universe_file, sectors)
    corr = run_layer("correlations", False, fetch_correlations, mctx, tickers, sectors)
    etf = run_layer("sector-etf-flows", False, fetch_etf_flows, mctx, sectors)
    flags = L.calendar_flags(D)

    all_lines: List[str] = []
    summary: Dict[str, Any] = {}
    net_gamma: Dict[str, Optional[float]] = {}
    all_core_ok = True
    for i, T in enumerate(tickers, 1):
        before = client.network_requests
        ctx = Ctx(client, T, D, cal, cfg, out_dir, cache_dir, today_ny, cutoff)
        res, derived = run_ticker(ctx, screener, skip)
        lines, core_ok, sup_ok, sup_n = ticker_log(T, res, derived, pit=cutoff is not None)
        all_core_ok &= core_ok == len(CORE_LAYERS)
        ge = res.get("greek-exposure")
        net_gamma[T] = ge.data["today"]["net_gamma"] if (ge and ge.ok) else None
        order = CORE_LAYERS + [n for n in res if n not in CORE_LAYERS]
        write_json(os.path.join(out_dir, T, "snapshot.json"), {
            "ticker": T, "group": W.group_of(T) or None, "target_date": D, "asof_cutoff": cutoff.isoformat() if cutoff else None,
            "prior_session": ctx.K if cutoff else None,
            "latest_trading_day": cal.latest(), "generated_at": now_ny.isoformat(timespec="seconds"),
            "tool_version": __version__,
            "coverage": {"core": f"{core_ok}/{len(CORE_LAYERS)}", "supplemental": f"{sup_ok}/{sup_n}"},
            "as_of": {n: res[n].as_of for n in order},
            "derived": derived,
            "layers": {n: res[n].to_json() for n in order},
        })
        summary[T] = {"coverage": {"core": f"{core_ok}/{len(CORE_LAYERS)}", "supplemental": f"{sup_ok}/{sup_n}"},
                      "layers": {n: {k: v for k, v in res[n].to_json().items() if k != "data"} for n in order}}
        all_lines += lines
        say(f"[{i}/{len(tickers)}] {T}: core {core_ok}/{len(CORE_LAYERS)}, supplemental {sup_ok}/{sup_n} "
            f"({client.network_requests - before} requests)")

    usage = client.last_usage
    head = [
        f"UW short-engine fetch · target {D}" + (f" as of {cutoff:%H:%M} ET" if cutoff else "")
        + f" · latest trading day {cal.latest()} · run {now_ny:%Y-%m-%d %H:%M %Z}",
        f"UW usage: daily used={usage.get('x-uw-daily-req-count', '?')}/{usage.get('x-uw-token-req-limit', '?')} · "
        f"this run: {client.network_requests} requests, {client.cache_hits} cache hits, {time.time() - t0:.0f}s",
    ] + [f"note: {n}" for n in head_notes] + [
        f"calendar: {flags['weekday']} · {flags['weekdays_to_month_end']} weekdays to month end ({flags['month_end']}) · "
        f"{flags['weekdays_to_quarter_end']} to quarter end · last quad witching {flags['last_quad_witching']} "
        f"({flags['days_since_quad_witching']}d ago)",
    ]
    for u in universes:
        if u.ok:
            d = u.data
            names = ", ".join(d["negative_names"]) or "none"
            head.append(f"universe [{d['label']}] as-of {d['as_of']}: net gamma < 0 → {d['negative']}/{d['n']} ({names}); null={d['null']}")
        else:
            head.append(u.log_line())
        head += [f"     note: {n}" for n in u.notes]
    groups = group_gamma(net_gamma)
    for g in groups:
        head.append(f"watchlist group [{g['label']}] net gamma < 0 → {g['negative']}/{g['n']}"
                    + (f" ({', '.join(g['negative_names'])})" if g["negative_names"] else "")
                    + (f"; missing {', '.join(g['missing'])}" if g["missing"] else ""))
    for r in (screener, corr, etf):
        head.append(r.log_line())
        head += [f"     note: {n}" for n in r.notes]

    log_text = "\n".join(head + all_lines) + "\n"
    with open(os.path.join(out_dir, "run_log.txt"), "w") as fh:
        fh.write(log_text)
    write_json(os.path.join(out_dir, "universe_gamma.json"), [u.to_json() for u in universes], indent=1)
    write_json(os.path.join(out_dir, "group_gamma.json"), groups, indent=1)
    write_json(os.path.join(out_dir, "market.json"), {
        "target_date": D, "calendar_flags": flags, "screener_batch": screener.to_json(),
        "correlations": corr.to_json(), "sector_etf_flows": etf.to_json()}, indent=1)
    write_json(os.path.join(out_dir, "run_summary.json"), {
        "target_date": D, "asof_cutoff": cutoff.isoformat() if cutoff else None,
        "latest_trading_day": cal.latest(), "generated_at": now_ny.isoformat(timespec="seconds"),
        "usage": usage, "requests": client.network_requests, "cache_hits": client.cache_hits,
        "universes": [{k: v for k, v in u.to_json().items() if k != "data"} for u in universes],
        "tickers": summary}, indent=1)
    say("")
    say(log_text)
    say(f"outputs: {out_dir}")
    return 0 if all_core_ok else 1
