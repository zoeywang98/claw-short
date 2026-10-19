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
from collections import defaultdict

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
        win[k] = pick(w, ["from", "to", "days_present", "poc", "dark_total", "regular_total",
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


FINVIZ_DIR = os.path.join(PROJECT_DIR, "finviz_si")   # <T>.json from workspace-claw-general/finviz/fv_short_interest.py
FINVIZ_MAX_LAG_DAYS = 3   # a Finviz file fetched more than this many days after D is not used (replays of old days)
CLOSE_REF_CONDS = ("prior_reference_price", "average_price_trade")
ML_CODES = {"mlet", "mlat", "mlct", "mlft", "tlet", "tlat", "tlct", "tlft"}   # UW multi-leg trade codes


def _tenor(dte):
    return "0-7d" if dte <= 7 else "8-30d" if dte <= 30 else "31-90d" if dte <= 90 else ">90d"


def _tape_items(L, target):
    """(type, dte, side, premium, legs, sweep, sym, size, oi) per print: option-trades when the fetch has them,
    else UW flow alerts (each alert split into its ask and bid premium). Futures-floor prints are left out."""
    import datetime as _dt
    trades = data(L, "option-trades").get("trades") or []
    for r in trades:
        if "futures_floor" in (r.get("report_flags") or []) or r.get("dte") is None:
            continue
        yield (r.get("type"), r["dte"], r.get("side"), r.get("premium") or 0,
               "multi" if r.get("code") in ML_CODES else "single", bool(r.get("sweep")), r.get("sym"),
               r.get("size"), r.get("open_interest"))
    if trades or not target:
        return
    d0 = _dt.date.fromisoformat(target)
    for a in data(L, "flow-alerts").get("alerts") or []:
        if a.get("floor") or not a.get("expiry"):
            continue
        dte = (_dt.date.fromisoformat(a["expiry"]) - d0).days
        legs = "multi" if a.get("multileg") else "single"
        for side in ("ask", "bid"):
            prem = a.get(f"{side}_premium") or 0
            if prem:
                yield (a.get("type"), dte, side, prem, legs, bool(a.get("sweep")), a.get("sym"), None,
                       a.get("open_interest"))


def _bucket_of(price, level_rows):
    """The price-levels bucket holding `price` (buckets are labelled by their lower edge)."""
    below = [r[0] for r in level_rows if r[0] is not None and r[0] <= price]
    return max(below) if below else None


def finviz_si(ticker, target):
    import datetime as _dt
    p = os.path.join(FINVIZ_DIR, f"{ticker}.json")
    if not os.path.exists(p):
        return {"status": "missing", "reason": f"no {p} (fv_short_interest.py not run, or Finviz/DICloak failed)"}
    doc = json.load(open(p))
    fetched = (doc.get("fetched_at") or "")[:10]
    if fetched and target and (_dt.date.fromisoformat(fetched) - _dt.date.fromisoformat(target)).days > FINVIZ_MAX_LAG_DAYS:
        return {"status": "not used", "reason": f"fetched {fetched}, more than {FINVIZ_MAX_LAG_DAYS} days after {target}"}
    from uwsf.layers import published_by   # past target: keep only settlements already public on that day
    rows = [r for r in doc.get("rows") or [] if not target or (r.get("date", "") <= target and
            (not fetched or fetched <= target or published_by(r["date"], target)))][:6]
    return {"source": doc.get("source"), "fetched_at": doc.get("fetched_at"), "page": doc.get("page"),
            "units": doc.get("units"), "rows": rows}


def template_inputs(snap, L):
    """Numbers for the fixed 7-section post (daily_short/INSTRUCTIONS.md, ZZ 2026-10-17). Data only: the wording
    rules live in INSTRUCTIONS.md."""
    der = snap.get("derived") or {}
    spot = (der.get("spot") or {}).get("mid")
    daily = data(L, "ohlc-daily")
    closes = {b[0]: b[4] for b in (daily.get("bars") or [])}
    out = {"spot": spot, "close": (daily.get("derived") or {}).get("close")}

    b4 = data(L, "ohlc-5m").get("bars_4h") or {}
    rows4 = (b4.get("rows") or [])[-20:]

    def halves(seg12):
        if len(seg12) != 12:
            return None
        return {name: {"from": f"{seg[0][0]} {seg[0][1]}", "to": f"{seg[-1][0]} {seg[-1][1]}",
                       "high": max(r[3] for r in seg), "low": min(r[4] for r in seg)}
                for name, seg in (("earlier_6", seg12[:6]), ("last_6", seg12[6:]))}
    out["bars_4h"] = {"columns": b4.get("columns"), "rows": rows4, "definition": b4.get("definition"),
                      "last_12_halves": halves(rows4[-12:]),
                      "prev_session_12_halves": halves(rows4[-14:-2])}   # same split one session (2 bars) earlier

    dl = data(L, "darkpool-levels")
    win = dl.get("windows") or {}
    per_day = {d: {**v, "levels": [[x.get("price"), x.get("dark"), x.get("regular")] if isinstance(x, dict) else x
                                   for x in (v.get("levels") or [])]}
               for d, v in (dl.get("per_day") or {}).items()}
    days = sorted(per_day)
    close_buckets = []
    for d in days[-5:]:
        lv = per_day[d]["levels"]
        c = closes.get(d)
        bk = _bucket_of(c, lv) if c is not None else None
        dark = sum(r[1] or 0 for r in lv if r[0] == bk) if bk is not None else None
        tot = per_day[d].get("dark_total")
        prices = sorted({r[0] for r in lv if r[0] is not None})
        i = prices.index(bk) if bk in prices else None
        adj = [p for p in (prices[i - 1] if i else None, prices[i + 1] if i is not None and i + 1 < len(prices) else None)
               if p is not None]
        nmax = max((sum(r[1] or 0 for r in lv if r[0] == p) for p in adj), default=None)
        close_buckets.append({"date": d, "close": c, "bucket": bk, "dark_in_bucket": dark,
                              "share_of_day_dark": (dark / tot) if (dark is not None and tot) else None,
                              "neighbors_max_dark": nmax,
                              "spike_vs_neighbors": (dark / nmax) if (dark and nmax) else None})
    prints = data(L, "darkpool").get("block_trades") or []   # D's block prints only
    ref = defaultdict(lambda: [0, 0, set()])
    for x in prints:
        if x.get("sale_cond") in CLOSE_REF_CONDS and x.get("price") is not None:
            a = ref[round(x["price"], 2)]
            a[0] += x.get("size") or 0
            a[1] += 1
            a[2].add(x["sale_cond"])
    D = snap.get("target_date")
    own_close = {cb["date"]: cb["bucket"] for cb in close_buckets}
    agg2 = defaultdict(float)
    for d in days[-2:]:
        lv = per_day[d]["levels"]
        minus = defaultdict(float)
        if d == D:   # D: take out the close-referenced block prints we can see, wherever they printed
            for p, v in ref.items():
                bk = _bucket_of(p, lv)
                if bk is not None:
                    minus[bk] += v[0]
        for r in lv:
            if r[0] is None or (d != D and r[0] == own_close.get(d)):   # earlier day: drop its closing-price bucket
                continue
            agg2[r[0]] += max((r[1] or 0) - minus.get(r[0], 0.0), 0.0)
    top2 = sorted(agg2.items(), key=lambda kv: -kv[1])[:6]
    clusters = []   # top-8 buckets grouped where neighbours are within 1% of price; heaviest group = main node
    for p, v in sorted(sorted(agg2.items(), key=lambda kv: -kv[1])[:8]):
        if clusters and p - clusters[-1]["high"] <= 0.01 * p:
            clusters[-1]["high"] = p
            clusters[-1]["dark"] += v
        else:
            clusters.append({"low": p, "high": p, "dark": v})
    main_cluster = max(clusters, key=lambda c: c["dark"]) if clusters else None
    # close vs 2D centroid, today and one session earlier: the "浅" tier in INSTRUCTIONS (ZZ 2026-10-18)
    c2d, close = (win.get("2D") or {}).get("centroid_top8"), out["close"]
    prev = None
    if len(days) >= 3:
        from uwsf.layers import level_stats   # same top-8 centroid the darkpool-levels layer uses for its windows
        agg = defaultdict(lambda: [0.0, 0.0])
        for d in days[-3:-1]:
            for p, dk, rg in per_day[d]["levels"]:
                if p is not None:
                    agg[p][0] += dk or 0.0
                    agg[p][1] += rg or 0.0
        pc2d, pclose = level_stats(dict(agg))["centroid_top8"], closes.get(days[-2])
        prev = {"date": days[-2], "close": pclose, "centroid_2D": pc2d,
                "close_below_2D": (pclose < pc2d) if (pclose is not None and pc2d) else None}
    m1, d1 = win.get("1M") or {}, win.get("1D") or {}
    avg = (m1.get("dark_total") / m1.get("days_present")) if m1.get("dark_total") and m1.get("days_present") else None
    out["dark_pool"] = {
        "windows": {k: pick(win.get(k) or {}, ["from", "to", "centroid_top8", "poc"]) for k in ("1D", "2D", "1W", "1M")},
        "dp_1d_vs_1m_avg": (d1["dark_total"] / avg) if (avg and d1.get("dark_total")) else None,
        "close_vs_2D": {"close": close, "centroid_2D": c2d,
                        "below_pct": ((c2d - close) / close * 100) if (close and c2d) else None,
                        "definition": "(2D centroid_top8 - close) / close * 100; positive = close below the 2D centroid"},
        "prev_session": prev,
        "prev_session_definition": "the session before window_end: its close and its own 2D window (that session + "
                                   "the one before), same top-8 centroid as darkpool_levels.windows",
        "close_buckets_5d": close_buckets,
        "top6_2d_ex_close_prints": {"rows": [[k, v] for k, v in top2],
                                    "low": min(k for k, _ in top2) if top2 else None,
                                    "high": max(k for k, _ in top2) if top2 else None,
                                    "main_cluster": main_cluster,
                                    "clusters_top8": clusters,
                                    "definition": "2D window dark volume by bucket, without closing-price prints: on D the "
                                                  "close_ref_prints_D block prints are subtracted from their buckets; on "
                                                  "the earlier day its whole closing-price bucket is left out"},
        "close_ref_prints_D": [[p, v[0], v[1], sorted(v[2])] for p, v in
                               sorted(ref.items(), key=lambda kv: -kv[1][0])[:5]],
        "close_ref_prints_columns": ["price", "shares", "prints", "sale_cond"],
    }

    ov = (data(L, "options-volume").get("series") or [])[-5:]
    day = ov[-1] if ov else {}
    prior = ov[:-1]
    keys = ("call_volume_ask_side", "call_volume_bid_side", "put_volume_ask_side", "put_volume_bid_side")
    prior_avg = {k: (sum(r.get(k) or 0 for r in prior) / len(prior)) if prior else None for k in keys}
    split, sweeps = defaultdict(float), defaultdict(float)
    far = defaultdict(lambda: defaultdict(lambda: [0.0, 0, None]))
    for typ, dte, side, prem, legs, sweep, sym, size, oi in _tape_items(L, snap.get("target_date")):
        split[f"{typ}|{_tenor(dte)}|{side}|{legs}"] += prem
        if sweep and dte <= 30:
            sweeps[f"{typ}|{side}"] += prem
        if dte > 90 and legs == "single" and side in ("ask", "bid"):
            a = far[f"{typ}|{side}"][sym]
            a[0] += prem
            a[1] += size or 0
            a[2] = oi
    tape_src = "option-trades" if data(L, "option-trades").get("trades") else \
        ("flow-alerts" if data(L, "flow-alerts").get("alerts") else "missing")
    out["options"] = {
        "day": pick(day, ["date", "call_premium", "put_premium", "net_call_premium", "net_put_premium", *keys]),
        "prior_4d_avg": prior_avg,
        "day_vs_prior_4d": {k: (day.get(k) / prior_avg[k]) if (day.get(k) and prior_avg.get(k)) else None for k in keys},
        "tape_premium_split": {"source": tape_src,
                               "definition": "option-trades premium >= $50k (fetch filter), futures_floor excluded; "
                                             "key = type|tenor|side|single-or-multi-leg (UW multi-leg codes). "
                                             "source flow-alerts = UW flow alerts' ask / bid premium (option-trades "
                                             "only serves the latest session, so past dates fall back to alerts)",
                               "premium": {k: round(v) for k, v in sorted(split.items())}},
        "sweeps_le_30d": {k: round(v) for k, v in sorted(sweeps.items())},
        "far_gt_90d_single_top3": {k: [[s, round(v[0]), v[1], v[2]] for s, v in
                                       sorted(c.items(), key=lambda kv: -kv[1][0])[:3]] for k, c in sorted(far.items())},
        "far_columns": ["sym", "premium", "contracts", "open_interest"],
    }

    ge = data(L, "greek-exposure")
    gx = data(L, "gex-levels")
    ges = data(L, "greek-exposure-strike")
    strikes = ges.get("strikes") or []
    near = [[s[0], s[1], s[2], s[3], s[6] if len(s) > 6 else None] for s in strikes
            if spot and s[0] is not None and spot * 0.8 <= s[0] <= spot * 1.2]
    below = [s for s in near if s[0] < (spot or 0)]
    above = [s for s in near if s[0] > (spot or 0)]
    dex_above = [s for s in strikes if spot and len(s) > 6 and spot < s[0] <= spot * 1.3]
    neg = [s for s in dex_above if (s[6] or 0) < 0]
    biggest = max((-s[6] for s in neg), default=0)
    dense = [s for s in neg if -s[6] >= 0.5 * biggest] if biggest else []
    first_pos = None
    if dense:   # above the last still-heavy negative strike, the first clearly positive one (tiny strikes ignored)
        last_heavy = max(s[0] for s in neg if -s[6] >= 0.25 * biggest)
        first_pos = next((s[0] for s in dex_above if s[0] > last_heavy and (s[6] or 0) >= 0.1 * biggest), None)
    out["dealer"] = {
        "net_gex_series": [pick(x, ["date", "net_gamma", "net_delta"]) for x in (ge.get("series_21d") or [])[-5:]],
        "gamma_flip": {"oi": (gx.get("latest_oi") or {}).get("gamma_flip"), "vol": (gx.get("latest") or {}).get("gamma_flip")},
        "walls": {src: pick(gx.get(k) or {}, ["call_wall", "put_wall", "gamma_magnet"])
                  for src, k in (("oi", "latest_oi"), ("vol", "latest"))},
        "strikes_spot_pm20pct": {"columns": ["strike", "call_gex", "put_gex", "net_gex", "net_dex"], "rows": near,
                                 "source": "greek-exposure/strike, open-interest basis"},
        "put_gamma_nodes_below_spot": [[s[0], s[2]] for s in sorted(below, key=lambda s: s[2] or 0)[:3]],
        "put_gamma_nodes_above_spot": [[s[0], s[2]] for s in sorted(above, key=lambda s: s[2] or 0)[:2]],
        "call_gamma_nodes_above_spot": [[s[0], s[1]] for s in sorted(above, key=lambda s: -(s[1] or 0))[:3]],
        "dex_above_spot": {"dense_negative": [[s[0], s[6]] for s in dense],
                           "dense_low": min((s[0] for s in dense), default=None),
                           "dense_high": max((s[0] for s in dense), default=None),
                           "first_positive_above_dense": first_pos,
                           "definition": "strikes in (spot, spot*1.3]; dense = net_dex < 0 and at least half of the "
                                         "most negative one; first_positive = first strike above the last strike "
                                         "still at <= -25% of the most negative, with net_dex >= +10% of it"},
    }

    iv = {r.get("days"): r.get("volatility") for r in (data(L, "interpolated-iv").get("term") or [])}
    ivrv = data(L, "iv-rv")
    sc = data(L, "screener")
    out["iv"] = {"interpolated": {f"{k}d": v for k, v in sorted(iv.items()) if k is not None},
                 "front_7d_minus_30d": (iv[7] - iv[30]) if (iv.get(7) is not None and iv.get(30) is not None) else None,
                 "iv30_last": (ivrv.get("iv30") or [None])[-1], "rv21_last": (ivrv.get("rv21_trailing") or [None])[-1],
                 "iv_rank": sc.get("iv_rank"), "iv_percentile_1y": sc.get("iv_percentile_1y")}

    si, sd, sv = data(L, "short-interest"), data(L, "short-data"), data(L, "short-volume")
    sd20 = sorted(sd.get("daily_last_20d") or [], key=lambda x: x.get("date") or "")
    sv20 = sorted(sv.get("series_20d") or [], key=lambda x: x.get("market_date") or "")
    out["short"] = {
        "uw_short_interest": {**pick(si.get("latest") or {}, ["market_date", "si_float", "days_to_cover"]),
                              "lag_days": si.get("lag_days")},
        "uw_borrow": {"latest": sd.get("latest"),
                      "5_sessions_ago": pick(sd20[-6], ["date", "fee_rate", "short_shares_available"]) if len(sd20) >= 6 else None},
        "uw_svr": [pick(x, ["market_date", "short_volume_ratio"]) for x in sv20[-3:]],
        "finviz": finviz_si(snap.get("ticker"), snap.get("target_date")),
    }
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
        "template_inputs": template_inputs(snap, L),
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
                             "chain_depth": data(L, "option-contracts").get("chain_depth"),
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
        "iv_rv": {k: (v[-45:] if isinstance(v, list) else v) for k, v in data(L, "iv-rv").items()},
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
    ap.add_argument("--cross-section", metavar="MARKET_BRIEF",
                    help="add the whole-watchlist cross-section (--tickers) to this market_brief.json and exit")
    ap.add_argument("--finviz-max-lag-days", type=int, default=FINVIZ_MAX_LAG_DAYS,
                    help="use finviz_si/<T>.json fetched up to this many days after --date (rows are always cut at "
                         "--date; raise it for a past date whose FINRA settlement was already public then)")
    a = ap.parse_args(argv)
    globals()["FINVIZ_MAX_LAG_DAYS"] = a.finviz_max_lag_days
    if a.cross_section:
        write_cross_section(a.cross_section, a.date, [t for t in a.tickers.split(",") if t])
        return 0
    day = os.path.join(a.data, a.date)
    tickers = [] if a.market_only else [t for t in a.tickers.split(",") if t] or sorted(
        t for t in os.listdir(day) if os.path.isfile(os.path.join(day, t, "snapshot.json")))
    if not a.no_market:
        write_market_brief(day)
    write_briefs(day, tickers)
    return 0


def write_market_brief(day):
    market = {}
    p = os.path.join(day, "market.json")
    if os.path.exists(p):
        mk = json.load(open(p))
        for k in ("calendar_flags", "correlations", "sector_etf_flows"):
            market[k] = mk.get(k)
    p = os.path.join(day, "group_gamma.json")
    if os.path.exists(p):
        groups = json.load(open(p))
        market["watchlist_group_gamma"] = [pick(g, ["label", "n", "negative", "negative_names", "missing"]) for g in groups]
        market["watchlist_breaker_board"] = {
            "negative": sum(g.get("negative") or 0 for g in groups), "n": sum(g.get("n") or 0 for g in groups),
            "negative_names": [t for g in groups for t in (g.get("negative_names") or [])],
            "rule": "SHORT_ENGINE §3: board = the watchlist; breaker trips at <= 4 negative-gamma names"}
    with open(os.path.join(day, "market_brief.json"), "w") as f:
        json.dump(rnd(market), f, ensure_ascii=False, separators=(",", ":"))


def snapshot_path(date, t):
    """Per-ticker run layout first (runs/tickers/<T>/<D>/<T>), then the all-at-once data/<D>/<T>."""
    for p in (os.path.join(PROJECT_DIR, "runs", "tickers", t, date, t, "snapshot.json"),
              os.path.join(PROJECT_DIR, "data", date, t, "snapshot.json")):
        if os.path.isfile(p):
            return p
    return None


def cross_row(snap):
    L = snap.get("layers") or {}
    der = snap.get("derived") or {}
    oh = data(L, "ohlc-daily").get("derived") or {}
    sv = data(L, "short-volume")
    svs = sorted(sv.get("series_20d") or [], key=lambda x: x.get("market_date") or "")
    dl = (data(L, "darkpool-levels").get("windows") or {})
    d1, m1 = dl.get("1D") or {}, dl.get("1M") or {}
    avg = (m1.get("dark_total") / m1.get("days_present")) if m1.get("dark_total") and m1.get("days_present") else None
    bp = ((der.get("block_participation") or {}).get("either") or {}).get("pct_total")
    sc = data(L, "screener")
    ge = (data(L, "greek-exposure").get("today") or {}).get("net_gamma")
    return [snap.get("ticker"), snap.get("group"), sc.get("sector"), oh.get("close"), oh.get("ret_1d"), oh.get("ret_5d"),
            oh.get("ret_21d"), svs[-1].get("short_volume_ratio") if svs else None,
            svs[-2].get("short_volume_ratio") if len(svs) > 1 else None, d1.get("dark_total"), avg,
            (d1["dark_total"] / avg) if (avg and d1.get("dark_total")) else None, d1.get("dp_pct"), bp, ge,
            sc.get("relative_volume"), sc.get("iv30d")]


CROSS_COLUMNS = ["ticker", "group", "sector", "close", "ret_1d", "ret_5d", "ret_21d", "svr", "svr_prev",
                 "dp_dark_1d", "dp_dark_1m_avg", "dp_1d_vs_1m_avg", "dp_pct_1d", "block_participation", "net_gamma",
                 "relative_volume", "iv30"]


def write_cross_section(market_brief, date, tickers):
    """Whole-watchlist cross-section in the market brief, so each ticker's read can see the board
    (SHORT_ENGINE §2 sector squeeze phase, §5.2 basket-shaped rebalance). Data only, no verdicts."""
    rows, missing = [], []
    for t in tickers:
        p = snapshot_path(date, t)
        if not p:
            missing.append(t)
            continue
        rows.append(cross_row(json.load(open(p))))
    groups = {}
    for r in rows:
        g = groups.setdefault(r[1] or "?", {"group": r[1], "n": 0, "up_1d": 0, "down_1d": 0, "ret_1d": [], "svr_ge_50": 0})
        g["n"] += 1
        if r[4] is not None:
            g["ret_1d"].append(r[4])
            g["up_1d" if r[4] > 0 else "down_1d"] += 1
        g["svr_ge_50"] += int((r[7] or 0) >= 0.5)
    for g in groups.values():
        v = g.pop("ret_1d")
        g["avg_ret_1d"] = (sum(v) / len(v)) if v else None
    m = json.load(open(market_brief))
    m["watchlist_cross_section"] = rnd({"date": date, "columns": CROSS_COLUMNS, "rows": rows, "missing": missing,
                                        "group_summary": list(groups.values()),
                                        "note": "ret_* from daily closes; svr = off-exchange short volume ratio (T+1); "
                                                "dp_* from darkpool-levels; block_participation = either-rule share of day volume"})
    with open(market_brief, "w") as f:
        json.dump(m, f, ensure_ascii=False, separators=(",", ":"))
    print(f"cross-section {len(rows)} rows" + (f", missing {','.join(missing)}" if missing else "") + f" -> {market_brief}")


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
