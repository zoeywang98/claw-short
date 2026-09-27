"""Phase-2 screen: apply the SHORT_ENGINE.md pipeline to fetched snapshots.

Reads data/<run>/<T>/snapshot.json (+ universe_gamma.json, group_gamma.json, market.json) and walks
① squeeze veto → ② circuit breaker → ③ magnitude → ④ direction → ⑤ motive → ⑥ dealer confirmation.
The doc gives no numbers for several gates; the interpretations live in TH so every ticker gets the same rules.
"""
from __future__ import annotations

import json
import os
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

TH: Dict[str, float] = {
    "fee_tight": 3.0,         # borrow fee % APR at/above which borrow counts as tight
    "avail_min": 200_000,     # sampled broker availability at/below which borrow counts as tight
    "avail_drop": 0.5,        # availability down ≥50% over the last 5 sessions → tight
    "si_high": 0.20,          # SI % float: background caution only (§1.3)
    "svr_high": 0.65,         # off-exchange short volume ratio: caution only
    "spike_atr": 3.0,         # 急涨: run-up (≤5 sessions, ending in the last 7) ≥ 3 ATR ...
    "spike_min": 0.10,        # ... and ≥ 10%
    "breaker_ratio": 4 / 35,  # ≤ 4/35 negative-gamma names in the pool → breaker
    "block_thin": 0.05,       # block participation below this = thin (doc: ~3-4% retail noise)
    "block_credible": 0.10,   # at/above this = credible (doc: ~16-21% institutional)
    "dp_vol_thin": 0.6,       # D dark volume below 0.6× its 20-session average = thin
    "centroid_eps": 0.005,    # 0.5% band for "flat" centroid moves
    "oi_up": 0.03, "oi_flat": 0.02, "iv_eps": 0.03, "vitality_hot": 1.2,
    "wall_near": 0.015,       # DP centroid within 1.5% of a wall / flip = clustered at structure
}


def _num(x: Any) -> Optional[float]:
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def _pct(x: Optional[float], d: int = 1) -> str:
    return "n/a" if x is None else f"{x * 100:.{d}f}%"


def _layer(s: Dict[str, Any], name: str) -> Optional[Dict[str, Any]]:
    l = s["layers"].get(name)
    return l["data"] if l and l["status"] == "RAN" else None


# --------------------------------------------------------------------------- steps
def step_veto(s: Dict[str, Any]) -> Dict[str, Any]:
    sd, sv, si = _layer(s, "short-data"), _layer(s, "short-volume"), _layer(s, "short-interest")
    daily = _layer(s, "ohlc-daily")
    sc = _layer(s, "screener") or {}
    out: Dict[str, Any] = {"reasons": [], "cautions": []}
    fee = _num(sd["latest"]["fee_rate"]) if sd else None
    avail = _num(sd["latest"]["short_shares_available"]) if sd else None
    series = [x for x in (sd or {}).get("daily_last_20d", [])]
    avail_5 = _num(series[5]["short_shares_available"]) if len(series) > 5 else None
    out.update(fee=fee, avail=avail, avail_5d_ago=avail_5)
    if fee is not None and fee >= TH["fee_tight"]:
        out["reasons"].append(f"借券费 {fee:.2f}%")
    if avail is not None and avail <= TH["avail_min"]:
        out["reasons"].append(f"可借仅 {avail:,.0f} 股")
    if avail and avail_5 and avail / avail_5 - 1 <= -TH["avail_drop"]:
        out["reasons"].append(f"可借 5 日内降 {1 - avail / avail_5:.0%}")
    svr = _num(sv["latest"]["short_volume_ratio"]) if sv else None
    si_f = _num(si["latest"]["si_float"]) if si else None
    out.update(svr=svr, si=si_f, si_date=si["latest"]["market_date"] if si else None)
    if svr is not None and svr >= TH["svr_high"]:
        out["cautions"].append(f"空头成交比 {_pct(svr)}")
    if si_f is not None and si_f >= TH["si_high"]:
        out["cautions"].append(f"SI {_pct(si_f)}（{out['si_date']}，背景）")
    # 急涨
    spike = None
    if daily:
        bars = daily["bars"]
        closes = [b[4] for b in bars]
        atr = _num(sc.get("atr_14")) or _num(daily["derived"].get("atr14_simple"))
        last = len(closes) - 1
        best = (0.0, None, None)
        for j in range(max(1, last - 6), last + 1):
            for i in range(max(0, j - 5), j):
                if closes[i] and closes[j] / closes[i] - 1 > best[0]:
                    best = (closes[j] / closes[i] - 1, bars[i][0], bars[j][0])
        if best[1]:
            i_close = closes[[b[0] for b in bars].index(best[1])]
            need = max(TH["spike_min"], TH["spike_atr"] * (atr or 0) / i_close) if i_close else TH["spike_min"]
            spike = {"runup": best[0], "from": best[1], "to": best[2], "threshold": need, "atr": atr,
                     "is_spike": best[0] >= need}
            if spike["is_spike"]:
                out["reasons"].append(f"急涨 {best[0]:+.1%}（{best[1][5:]}→{best[2][5:]}，门槛 {need:.1%}）")
    out["spike"] = spike
    out["triggered"] = bool(out["reasons"])
    return out


def step_breaker(s: Dict[str, Any], universes: List[Dict[str, Any]], groups: List[Dict[str, Any]]) -> Dict[str, Any]:
    sector = (_layer(s, "screener") or {}).get("sector")
    ge = _layer(s, "greek-exposure")
    own = _num(ge["today"]["net_gamma"]) if ge else None
    pool = None
    for u in universes:
        d = u.get("data") or {}
        if u.get("status") == "RAN" and sector and str(d.get("label", "")).startswith(sector):
            pool = d
    out: Dict[str, Any] = {"sector": sector, "own_net_gamma": own}
    if pool:
        ratio = pool["negative"] / pool["n"] if pool["n"] else None
        out.update(pool=pool["label"], negative=pool["negative"], n=pool["n"],
                   triggered=ratio is not None and ratio <= TH["breaker_ratio"])
    else:
        out.update(pool=None, negative=None, n=None, triggered=None)  # ETF / unknown sector: no pool
    g = next((g for g in groups if s["ticker"] in g.get("net_gamma", {}) or s["ticker"] in g.get("missing", [])), None)
    if g:
        out["group"] = f"{g['label']} {g['negative']}/{g['n']}"
    return out


def step_magnitude(s: Dict[str, Any]) -> Dict[str, Any]:
    bp = (s.get("derived") or {}).get("block_participation") or {}
    part = (bp.get("either") or {}).get("pct_total")
    dl = _layer(s, "darkpool-levels")
    dark_d, avg = None, None
    if dl:
        days = sorted(dl["per_day"].items())
        dark_d = days[-1][1]["dark_total"]
        prev = [v["dark_total"] for _, v in days[-21:-1]]
        avg = sum(prev) / len(prev) if prev else None
    rel = (dark_d / avg) if (dark_d and avg) else None
    week_rel = None
    if dl:
        w, m = dl["windows"]["1W"], dl["windows"]["1M"]
        if w["days_present"] and m["days_present"] and m["dark_total"]:
            week_rel = (w["dark_total"] / w["days_present"]) / (m["dark_total"] / m["days_present"])
    # thin = retail-noise block share, or a quiet DP day without institutional share to back it
    thin = (part is not None and part < TH["block_thin"]) or \
           (rel is not None and rel < TH["dp_vol_thin"] and (part is None or part < TH["block_credible"]))
    label = "thin" if thin else ("credible" if (part or 0) >= TH["block_credible"] else "moderate")
    return {"participation": part, "dark_d": dark_d, "dark_avg20": avg, "dark_rel": rel, "dark_week_rel": week_rel, "label": label}


def step_direction(s: Dict[str, Any]) -> Dict[str, Any]:
    dl = _layer(s, "darkpool-levels")
    daily = _layer(s, "ohlc-daily")
    if not dl:
        return {"label": "n/a"}
    w = dl["windows"]
    c1, cw, cm = w["1D"]["centroid_top8"], w["1W"]["centroid_top8"], w["1M"]["centroid_top8"]
    close = daily["derived"]["close"] if daily else None
    e = TH["centroid_eps"]
    if c1 > cw * (1 + e) and cw > cm * (1 + e):
        label = "up"
    elif c1 <= cw * (1 + e) and cw <= cm * (1 + e):
        label = "down/flat"
    else:
        label = "mixed"
    top = [t["price"] for t in w["1D"]["top8"]]
    below_levels = close is not None and top and close < min(top)
    return {"label": label, "c1D": c1, "c1W": cw, "c1M": cm, "close": close,
            "close_vs_c1D": (close / c1 - 1) if (close and c1) else None, "below_all_1D_levels": bool(below_levels),
            "dp_pct_1D": w["1D"]["dp_pct"], "dp_pct_1M": w["1M"]["dp_pct"]}


def _opex_start(series: List[Dict[str, Any]], D: str) -> int:
    """Index of the first session after the last monthly opex (avoids expiry OI drops)."""
    d0 = date.fromisoformat(D)
    first = date(d0.year, d0.month, 1)
    opex = first.toordinal() + (4 - first.weekday()) % 7 + 14
    opex_d = date.fromordinal(opex)
    if opex_d > d0:  # previous month's opex
        pm = date(d0.year - (d0.month == 1), (d0.month - 2) % 12 + 1, 1)
        opex_d = date.fromordinal(pm.toordinal() + (4 - pm.weekday()) % 7 + 14)
    idx = [i for i, r in enumerate(series) if r["date"] > opex_d.isoformat()]
    i = idx[0] if idx else max(0, len(series) - 6)
    return i if len(series) - 1 - i >= 2 else max(0, len(series) - 6)


def step_motive(s: Dict[str, Any], direction: Dict[str, Any], magnitude: Dict[str, Any],
                market: Dict[str, Any]) -> Dict[str, Any]:
    ov = _layer(s, "options-volume")
    sc = _layer(s, "screener") or {}
    rr = _layer(s, "rr-skew")
    gex = _layer(s, "gex-levels")
    dp = _layer(s, "darkpool")
    D = s["target_date"]
    m: Dict[str, Any] = {}
    if ov and ov["series"]:
        ser = ov["series"]
        i0 = _opex_start(ser, D)
        a, b = ser[i0], ser[-1]
        m["oi_window"] = f"{a['date'][5:]}→{b['date'][5:]}"
        m["call_oi_chg"] = (b["call_open_interest"] / a["call_open_interest"] - 1) if a.get("call_open_interest") else None
        m["put_oi_chg"] = (b["put_open_interest"] / a["put_open_interest"] - 1) if a.get("put_open_interest") else None
        vol = (b.get("call_volume") or 0) + (b.get("put_volume") or 0)
        avg = (b.get("avg_30_day_call_volume") or 0) + (b.get("avg_30_day_put_volume") or 0)
        m["vitality"] = vol / avg if avg else None
        m["net_call_prem"], m["net_put_prem"] = b.get("net_call_premium"), b.get("net_put_premium")
    iv, iv1w, iv1m = _num(sc.get("iv30d")), _num(sc.get("iv30d_1w")), _num(sc.get("iv30d_1m"))
    m["iv"], m["iv_1w"], m["iv_1m"], m["iv_rank"] = iv, iv1w, iv1m, _num(sc.get("iv_rank"))
    m["iv_trend"] = (iv / iv1w - 1) if (iv and iv1w) else None
    if rr and len(rr["series"]) >= 6:
        m["rr_now"], m["rr_5d"] = rr["series"][-1]["risk_reversal"], rr["series"][-6]["risk_reversal"]
    e = TH["iv_eps"]
    # earnings that rolled into the 30-day IV window during the last week inflate iv30d vs iv30d_1w
    ed = sc.get("next_earnings_date")
    m["earnings"] = ed
    m["earnings_days"] = (date.fromisoformat(ed) - date.fromisoformat(D)).days if ed else None
    iv_contaminated = m["earnings_days"] is not None and 23 < m["earnings_days"] <= 30
    m["iv_earnings_contaminated"] = iv_contaminated
    call_chg, put_chg = m.get("call_oi_chg"), m.get("put_oi_chg")
    big_dp = (magnitude.get("dark_rel") or 0) >= 0.8 or (magnitude.get("dark_week_rel") or 0) >= 1.0
    crit: Dict[str, Optional[bool]] = {
        "a_dp_big_high_levels_not_up": direction.get("label") == "down/flat" and big_dp
        and (direction.get("dp_pct_1D") or 0) >= (direction.get("dp_pct_1M") or 1) * 0.95,
        "b_price_stall": (direction.get("close_vs_c1D") or 0) < 0,
        "c_call_oi_flat_or_put_oi_up": (call_chg is not None and call_chg <= TH["oi_flat"])
        or ((put_chg or 0) >= TH["oi_up"] and (put_chg or 0) > (call_chg or 0)),
        "d_iv_flat_or_compressing": None if iv_contaminated else (m.get("iv_trend") is not None and m["iv_trend"] <= e),
        "e_vitality_flat_or_contracting": m.get("vitality") is not None and m["vitality"] <= 1.0,
        "f_upside_tail_contracting": m.get("rr_now") is not None and m.get("rr_5d") is not None and m["rr_now"] > m["rr_5d"],
    }
    m["distribution_criteria"] = crit
    rest = [v for k, v in crit.items() if k != "a_dp_big_high_levels_not_up" and v is not None]
    need = 3 if len(rest) >= 5 else max(2, len(rest) - 1)
    dist_hit = bool(crit["a_dp_big_high_levels_not_up"]) and sum(1 for v in rest if v) >= need
    m["distribution_need"] = f"{sum(1 for v in rest if v)}/{len(rest)} (need {need})"
    # exclusions
    iv_up = (not iv_contaminated) and m.get("iv_trend") is not None and m["iv_trend"] > e
    call_up = (m.get("call_oi_chg") or 0) >= TH["oi_up"]
    put_up = (m.get("put_oi_chg") or 0) >= TH["oi_up"]
    ah = (((dp or {}).get("blocks") or {}).get("after_hours") or {}).get("pct_of_day_volume") or 0
    near = None
    if gex and direction.get("c1D"):
        lv = gex["latest"]
        lvls = [x for x in (lv.get("call_wall"), lv.get("put_wall"), lv.get("gamma_flip")) if x]
        if lvls:
            near = min(abs(direction["c1D"] / x - 1) for x in lvls)
    flags = market.get("calendar_flags", {})
    period_end = (flags.get("weekdays_to_quarter_end", 99) <= 5) or (flags.get("weekdays_to_month_end", 99) <= 3)
    close = direction.get("close")
    flip = (gex or {}).get("latest", {}).get("gamma_flip") if gex else None
    alts = {
        "吸筹": sum([direction.get("label") == "up", call_up, iv_up and (m.get("iv_rank") or 100) < 30, (direction.get("close_vs_c1D") or -1) >= 0]),
        "库存转移": sum([ah >= 0.01, call_up, iv_up, (m.get("vitality") or 0) >= TH["vitality_hot"]]),
        "Gamma对冲": sum([near is not None and near <= TH["wall_near"], direction.get("label") == "mixed", not iv_up]),
        "对冲/领口": sum([put_up, (m.get("net_call_prem") or 0) < 0, not iv_up, bool(close and flip and close >= flip)]),
        "再平衡": sum([period_end, abs(m.get("call_oi_chg") or 0) < TH["oi_flat"] and abs(m.get("put_oi_chg") or 0) < TH["oi_flat"],
                     abs(m.get("iv_trend") or 0) < e]),
    }
    denom = {"吸筹": 4, "库存转移": 4, "Gamma对冲": 3, "对冲/领口": 4, "再平衡": 3}
    best = max(alts, key=lambda k: alts[k] / denom[k])
    # the doc's discriminator: distribution never coexists with Call OI + IV + vitality all rising
    inv_block = call_up and iv_up and (m.get("vitality") or 0) >= TH["vitality_hot"]
    m.update(distribution_hit=bool(dist_hit and not inv_block), alt_scores={k: f"{alts[k]}/{denom[k]}" for k in alts},
             best_alt=best, best_alt_score=alts[best] / denom[best], after_hours_block_pct=ah, centroid_near_structure=near)
    return m


def step_dealer(s: Dict[str, Any], motive: Dict[str, Any], direction: Dict[str, Any]) -> Dict[str, Any]:
    gex, oc = _layer(s, "gex-levels"), _layer(s, "oi-change")
    pts: Dict[str, Optional[bool]] = {}
    if gex:
        dod = (gex.get("day_over_day_change") or {}).get("vol") or {}
        pts["structure"] = (dod.get("call_wall") is not None and dod["call_wall"] <= 0) or (dod.get("gamma_flip") or 0) < 0
    # net bearish premium = (put ask - put bid) - (call ask - call bid)
    pts["flow_bearish"] = ((motive.get("net_put_prem") or 0) - (motive.get("net_call_prem") or 0)) > 0
    pts["next_day_oi"] = None  # D's flow is confirmed by D+1 pre-open OI, not yet published
    if oc:  # stale proxy: D's OI change reflects D-1 trading
        sto = sum(c["oi_diff"] for c in oc["contracts"] if c["type"] == "call" and (c["oi_diff"] or 0) > 0
                  and (c["prev_bid_volume"] or 0) > (c["prev_ask_volume"] or 0))
        bto = sum(c["oi_diff"] for c in oc["contracts"] if c["type"] == "call" and (c["oi_diff"] or 0) > 0
                  and (c["prev_ask_volume"] or 0) > (c["prev_bid_volume"] or 0))
        pts["prior_day_call_sto_dominant"] = sto > bto
    close, flip = direction.get("close"), (gex or {}).get("latest", {}).get("gamma_flip") if gex else None
    pts["price_below_flip"] = bool(close and flip and close < flip)
    score = sum(1 for k in ("structure", "flow_bearish", "price_below_flip") if pts.get(k))
    return {"points": pts, "score_of_3_available": score}


def levels(s: Dict[str, Any], direction: Dict[str, Any]) -> Dict[str, Optional[float]]:
    gex = _layer(s, "gex-levels")
    close = direction.get("close")
    if not gex or not close:
        return {}
    lv = gex["latest"]
    flip, cw, pw = lv.get("gamma_flip"), lv.get("call_wall"), lv.get("put_wall")
    if flip and close < flip:  # already below the flip: trigger met, invalidation is a flip reclaim
        decision = "below flip"
        invalid = flip
    else:
        decision = flip if flip else pw
        invalid = cw if (cw and cw > close) else None
    return {"decision_line": decision, "invalidation": invalid, "call_wall": cw, "put_wall": pw, "gamma_flip": flip}


# --------------------------------------------------------------------------- run
def screen(run_dir: str) -> Dict[str, Any]:
    load = lambda n: json.load(open(os.path.join(run_dir, n))) if os.path.exists(os.path.join(run_dir, n)) else []
    universes, groups, market = load("universe_gamma.json"), load("group_gamma.json"), load("market.json") or {}
    results = []
    for T in sorted(d for d in os.listdir(run_dir) if os.path.isfile(os.path.join(run_dir, d, "snapshot.json"))):
        s = json.load(open(os.path.join(run_dir, T, "snapshot.json")))
        veto = step_veto(s)
        brk = step_breaker(s, universes, groups)
        mag = step_magnitude(s)
        dirn = step_direction(s)
        mot = step_motive(s, dirn, mag, market)
        dealer = step_dealer(s, mot, dirn)
        lv = levels(s, dirn)
        if veto["triggered"]:
            verdict, why = "🚫 挤仓否决", "；".join(veto["reasons"])
        elif brk.get("triggered"):
            verdict, why = "⛔ 熔断", f"{brk['pool']} 负 gamma {brk['negative']}/{brk['n']}"
        elif mag["label"] == "thin":
            verdict, why = "— 量太薄", f"大单参与度 {_pct(mag['participation'])}，暗池量 {mag['dark_rel'] or 0:.2f}× 20 日均值"
        elif dirn["label"] == "up":
            verdict, why = "✖ 吸筹形态", f"重心 1M {dirn['c1M']:.2f} → 1W {dirn['c1W']:.2f} → 1D {dirn['c1D']:.2f} 上移"
        elif not mot["distribution_hit"]:
            verdict, why = "✖ 未命中派发", f"方向 {dirn['label']}；最像 {mot['best_alt']}（{mot['alt_scores'][mot['best_alt']]}）"
        else:
            verdict = "👀 派发，待次日 OI" if dealer["score_of_3_available"] >= 2 else "👀 派发，dealer 确认不足"
            why = f"派发 {mot['distribution_need']}；dealer {dealer['score_of_3_available']}/3（次日 OI 未出）"
        if not brk.get("sector") and (s.get("group") or "").endswith("ETF"):
            why += "；ETF：暗池/dealer 指纹按个股设计，置信度低"
        if mot.get("earnings_days") is not None and mot["earnings_days"] <= 30:
            why += f"；{mot['earnings_days']} 天后财报"
        results.append({"ticker": T, "group": s.get("group"), "as_of": s["target_date"], "verdict": verdict, "why": why,
                        "veto": veto, "breaker": brk, "magnitude": mag, "direction": dirn, "motive": mot,
                        "dealer": dealer, "levels": lv})
    return {"run": run_dir, "thresholds": TH, "results": results}
