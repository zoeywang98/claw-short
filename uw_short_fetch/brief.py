#!/usr/bin/env python3
"""Compact each ticker's snapshot.json into brief.json for SHORT_ENGINE reads (no verdicts here).

snapshot.json is 2-11 MB per ticker. brief.json keeps the fields SHORT_ENGINE sections 2-8 read, including
the raw record lists (block trades, option trades, per-day DP levels, every OI-change / option contract),
re-encoded as {"columns": [...], "rows": [[...]]} tables so no field is lost but keys are not repeated per row.
Dropped: layers the engine never reads (spot-gex, options-pulse intraday, offlit-levels, greek-exposure-strike,
lit-blocks raw prints, other names' screener rows) and constant per-row fields hoisted to the table header.

usage: python3 brief.py --date YYYY-MM-DD [--tickers NBIS,AXTI]
"""
import argparse
import json
import os
import sys

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
CORE = ["darkpool-levels", "darkpool", "option-trades", "gex-levels",
        "greek-exposure", "short-interest", "short-volume", "short-data"]


def rnd(o):
    if isinstance(o, float):
        return float(f"{o:.6g}")
    if isinstance(o, dict):
        return {k: rnd(v) for k, v in o.items()}
    if isinstance(o, list):
        return [rnd(v) for v in o]
    return o


def table(rows, drop=(), **const):
    """List of dicts -> columnar table; `drop` removes fields, `const` records hoisted constant fields."""
    rows = rows or []
    cols = [c for c in (rows[0].keys() if rows else []) if c not in drop]
    t = {"columns": cols, "rows": [[r.get(c) for c in cols] for r in rows]}
    if const:
        t["constant"] = const
    return t


OVERSIZE_BYTES = 1_200_000   # unfiltered brief above this gets filter tier 1
MAX_BRIEF_BYTES = 1_450_000  # after tier 1, keep tightening until under this (~0.9M tokens at ~1.6 chars/token;
                             # the model's context is 1M and META at 1.64 MB measured 946k input tokens)
# (strike band around spot, max days to expiry, min dark-pool block premium) - tried in order
TIERS = [
    (0.30, 180, 1_000_000),
    (0.30, 90, 1_000_000),
    (0.20, 90, 2_000_000),
    (0.15, 45, 5_000_000),
]


class Filt:
    """Strike/expiry filter for option-level rows; inactive unless the brief is oversized."""

    def __init__(self, spot=None, target=None, tier=None):
        import datetime as _dt
        self.active = bool(tier is not None and spot)
        self.tier = tier
        band, self.max_dte, self.block_min = TIERS[tier] if tier is not None else (0, 0, 0)
        self.band = band
        self.lo, self.hi = (spot * (1 - band), spot * (1 + band)) if spot else (None, None)
        self.last_expiry = (_dt.date.fromisoformat(target) + _dt.timedelta(days=self.max_dte)).isoformat() \
            if target and tier is not None else None

    def strike_ok(self, k):
        return not self.active or k is None or self.lo <= k <= self.hi

    def rec_ok(self, r):
        if not self.active:
            return True
        e = r.get("expiry")
        return self.strike_ok(r.get("strike")) and (e is None or self.last_expiry is None or e <= self.last_expiry)

    def recs(self, rows):
        return [r for r in (rows or []) if self.rec_ok(r)]

    def strike_rows(self, rows):
        """Columnar rows whose first column is the strike."""
        return [r for r in (rows or []) if self.strike_ok(r[0] if r else None)]


def pick(d, keys):
    return {k: d.get(k) for k in keys if isinstance(d, dict) and k in d}


def data(layers, name):
    return (layers.get(name) or {}).get("data") or {}


def layer_log(layers):
    """One line per core layer, SHORT_ENGINE section 8 format."""
    lines = []
    for name in CORE:
        L = layers.get(name) or {}
        if L.get("status") == "RAN":
            extra = f" {L['extra']}" if L.get("extra") else ""
            lines.append(f"✅ RAN {name} as-of {L.get('as_of')} rows={L.get('rows')}{extra}")
        else:
            lines.append(f"❌ FAIL {name} reason: {L.get('reason') or 'missing layer'}")
    return lines


def dp_levels(layers):
    d = data(layers, "darkpool-levels")
    win = {}
    for k, w in (d.get("windows") or {}).items():
        win[k] = pick(w, ["from", "to", "days_present", "dark_total", "regular_total",
                          "dp_pct", "centroid_top8", "dark_vwap_all"])
        win[k]["top8"] = [pick(x, ["price", "dark", "regular", "dp_pct"]) for x in w.get("top8", [])]
    per_day = {}
    for day, v in (d.get("per_day") or {}).items():
        per_day[day] = {k: v.get(k) for k in ("dark_total", "regular_total", "dp_pct", "centroid_top8", "top8_prices")}
        lv = v.get("levels") or []
        per_day[day]["levels"] = {"columns": ["price", "dark", "regular"], "rows": lv} if lv and isinstance(lv[0], list) \
            else table(lv)
    return {"windows": win, "snapshots": d.get("snapshots"), "per_day": per_day}


def darkpool(layers, f):
    d = data(layers, "darkpool")
    blocks = d.get("blocks") or {}
    out = pick(d, ["spot", "spot_rth_close", "day_volume"])
    out["blocks"] = {k: blocks[k] for k in ("either", "by_size", "by_premium", "after_hours", "auction") if k in blocks}
    out["largest"] = [pick(x, ["et", "price", "size", "premium", "nbbo_mid", "ext_hours", "sale_cond"])
                      for x in (blocks.get("largest") or [])[:8]]
    prints = d.get("block_trades") or []
    if f.active:
        prints = [x for x in prints if (x.get("premium") or 0) >= f.block_min]
    out["block_trades"] = table(prints, drop=("executed_at",), time_zone="et = New York time")
    return out


def option_trades(layers, f):
    d = data(layers, "option-trades")
    agg = dict(d.get("aggregates") or {})
    agg["top_contracts"] = (agg.get("top_contracts") or [])[:12]
    agg.pop("strike_mismatch_examples", None)
    trades = table(f.recs(d.get("trades")), drop=("underlying_price_unreliable",))
    return {"min_premium": d.get("min_premium"), "truncated": d.get("truncated"), "aggregates": agg, "trades": trades}


def gex(layers):
    d = data(layers, "gex-levels")
    out = pick(d, ["levels_date", "day_over_day_change"])
    for k in ("latest", "latest_oi"):
        if k in d:
            out[k] = {kk: vv for kk, vv in d[k].items() if kk != "nearby_flips"}
    out["series"] = {src: [pick(x, ["date", "call_wall", "put_wall", "gamma_flip", "gamma_magnet"]) for x in rows]
                     for src, rows in (d.get("series") or {}).items()}
    return out


def build(snap, tier=None):
    L = snap.get("layers") or {}
    f = Filt(((snap.get("derived") or {}).get("spot") or {}).get("mid"), snap.get("target_date"), tier)
    ge = data(L, "greek-exposure")
    si = data(L, "short-interest")
    sv = data(L, "short-volume")
    sd = data(L, "short-data")
    oc = data(L, "oi-change")
    oc_keys = ["sym", "type", "strike", "expiry", "dte", "curr_oi", "last_oi", "oi_diff", "prev_ask_volume"]
    ml = data(L, "multi-leg").get("per_day") or {}
    brief = {
        "ticker": snap.get("ticker"), "group": snap.get("group"), "target_date": snap.get("target_date"),
        "coverage": snap.get("coverage"), "as_of": snap.get("as_of"),
        "run_log_core": layer_log(L),
        "derived": snap.get("derived"),
        "darkpool_levels": dp_levels(L),
        "darkpool": darkpool(L, f),
        "option_trades": option_trades(L, f),
        "gex_levels": gex(L),
        "greek_exposure": {"today": ge.get("today"),
                           "series_21d": [pick(x, ["date", "net_gamma", "net_delta"]) for x in ge.get("series_21d", [])]},
        "short_interest": {"latest": si.get("latest"), "lag_days": si.get("lag_days"),
                           "series": [pick(x, ["market_date", "si_float", "days_to_cover", "fee_rate", "short_shares_available"])
                                      for x in si.get("series", [])]},
        "short_volume": {"latest": sv.get("latest"),
                         "ratio_20d": [pick(x, ["market_date", "short_volume_ratio"]) for x in sv.get("series_20d", [])]},
        "short_data": {"latest": sd.get("latest"),
                       "daily_20d": [pick(x, ["date", "fee_rate", "short_shares_available"]) for x in sd.get("daily_last_20d", [])]},
        "price": {"derived": data(L, "ohlc-daily").get("derived"),
                  "columns": data(L, "ohlc-daily").get("columns"),
                  "last_22_bars": sorted(data(L, "ohlc-daily").get("bars") or [])[-22:]},
        "oi_change": {"totals": oc.get("totals"),
                      "top_increase": [pick(x, oc_keys) for x in (oc.get("top_increase") or [])[:12]],
                      "top_decrease": [pick(x, oc_keys) for x in (oc.get("top_decrease") or [])[:12]],
                      "contracts": table([x for x in f.recs(oc.get("contracts")) if x.get("oi_diff")],
                                         drop=("curr_date", "last_date"),
                                         rows_with_oi_diff_0_removed=sum(1 for x in (oc.get("contracts") or []) if not x.get("oi_diff")),
                                         curr_date=(oc.get("contracts") or [{}])[0].get("curr_date"),
                                         last_date=(oc.get("contracts") or [{}])[0].get("last_date"))},
        "oi_per_strike": {**data(L, "oi-per-strike"), "strikes": f.strike_rows(data(L, "oi-per-strike").get("strikes"))},
        "option_contracts": {"filter": data(L, "option-contracts").get("filter"),
                             "contracts": table(f.recs(data(L, "option-contracts").get("contracts")))},
        "contract_history": {"selection": data(L, "contract-history").get("selection"),
                             "contracts": {sym: table(rows) for sym, rows in
                                           (dict(data(L, "contract-history").get("contracts")) if isinstance(data(L, "contract-history").get("contracts"), list)
                                            else (data(L, "contract-history").get("contracts") or {})).items()}},
        "flow_per_strike": {**data(L, "flow-per-strike"),
                            "days": {day: f.strike_rows(rows) for day, rows in (data(L, "flow-per-strike").get("days") or {}).items()}},
        "flow_alerts": {**data(L, "flow-alerts"), "alerts": table(f.recs(data(L, "flow-alerts").get("alerts")))},
        "ohlc_5m": data(L, "ohlc-5m"),
        "options_volume_5d": (data(L, "options-volume").get("series") or [])[-5:],
        "interpolated_iv": data(L, "interpolated-iv").get("term"),
        "option_sentiment": {"latest": data(L, "option-sentiment").get("latest"),
                             "history_10": (data(L, "option-sentiment").get("history_30") or [])[-10:]},
        "rr_skew_25d": {"expiry": data(L, "rr-skew").get("expiry"),
                        "series_10": (data(L, "rr-skew").get("series") or [])[-10:]},
        "multi_leg": {day: {"count": v.get("count"), "by_strategy_side": v.get("by_strategy_side"),
                            "risk_reversals": v.get("risk_reversals"),
                            "strategies": table(v.get("strategies"), drop=("id",))}
                      for day, v in sorted(ml.items())},
        "screener": data(L, "screener"),
        "unusualness": data(L, "unusualness"),
        "options_pulse_latest": data(L, "options-pulse").get("latest"),
    }
    if f.active:
        brief["filter_applied"] = {
            "tier": f"{f.tier + 1}/{len(TIERS)}",
            "reason": f"unfiltered brief over {OVERSIZE_BYTES // 1000} KB; tiers tightened until under "
                      f"{MAX_BRIEF_BYTES // 1000} KB",
            "rule": f"option-level rows kept only for strikes {f.lo:.2f}-{f.hi:.2f} (spot +/-{f.band:.0%}) "
                    f"and expiries <= {f.last_expiry} ({f.max_dte}d)",
            "applies_to": "option_trades.trades, oi_change.contracts, option_contracts, oi_per_strike, "
                          "flow_per_strike, flow_alerts.alerts; darkpool.block_trades kept only at premium >= "
                          f"${f.block_min:,}",
            "note": "aggregates / totals / top lists were computed by fetch.py on the unfiltered data"}
    return rnd(brief)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="brief.py")
    ap.add_argument("--date", required=True)
    ap.add_argument("--tickers", default="")
    ap.add_argument("--data", default=os.path.join(PROJECT_DIR, "data"))
    ap.add_argument("--market-only", action="store_true", help="write market_brief.json only (no per-ticker briefs)")
    ap.add_argument("--no-market", action="store_true", help="write per-ticker briefs only")
    a = ap.parse_args(argv)
    day = os.path.join(a.data, a.date)
    tickers = [] if a.market_only else [t for t in a.tickers.split(",") if t] or sorted(
        t for t in os.listdir(day) if os.path.isfile(os.path.join(day, t, "snapshot.json")))
    if not a.no_market:
        write_market_brief(day)
    write_briefs(day, tickers)
    return 0


def write_market_brief(day):
    market = {}
    p = os.path.join(day, "universe_gamma.json")
    if os.path.exists(p):
        market["universe_gamma"] = [
            {"status": u.get("status"), **pick(u.get("data") or {}, ["label", "as_of", "n", "negative", "negative_names", "null"])}
            for u in json.load(open(p))]
    p = os.path.join(day, "market.json")
    if os.path.exists(p):
        mk = json.load(open(p))
        for k in ("calendar_flags", "correlations", "sector_etf_flows"):
            market[k] = mk.get(k)
    p = os.path.join(day, "group_gamma.json")
    if os.path.exists(p):
        market["watchlist_group_gamma"] = [pick(g, ["label", "n", "negative", "negative_names", "missing"]) for g in json.load(open(p))]
    with open(os.path.join(day, "market_brief.json"), "w") as f:
        json.dump(rnd(market), f, ensure_ascii=False, separators=(",", ":"))


def write_briefs(day, tickers):
    for t in tickers:
        snap = json.load(open(os.path.join(day, t, "snapshot.json")))
        out = os.path.join(day, t, "brief.json")
        text = json.dumps(build(snap), ensure_ascii=False, separators=(",", ":"))
        tier = None
        if len(text.encode()) > OVERSIZE_BYTES:
            for tier in range(len(TIERS)):
                text = json.dumps(build(snap, tier), ensure_ascii=False, separators=(",", ":"))
                if len(text.encode()) <= MAX_BRIEF_BYTES:
                    break
        with open(out, "w") as f:
            f.write(text)
        size = os.path.getsize(out)
        note = "" if tier is None else f" filter tier {tier + 1}/{len(TIERS)}"
        if size > MAX_BRIEF_BYTES:
            note += " WARNING: still over limit after last tier"
        print(f"{t} {size}B{note}")


if __name__ == "__main__":
    sys.exit(main())
