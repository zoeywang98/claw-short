"""Per-layer fetchers and normalizers.

Every layer returns a LayerResult. Layers only fetch and reshape data; they never
emit trading verdicts (squeeze veto, circuit breaker, fingerprints are phase 2).

Payload quirks handled here (SHORT_ENGINE.md §7 plus what live testing showed):
- greek-exposure / SI / short-volume / short-data: pick the row for the target
  date (max date <= D), never the first or last row.
- short-volume rows live under `si`; gex-levels `data` is a dict; flow-per-strike
  is a bare list; option-contract historic rows live under `chains`.
- ohlc/1d comes back newest-first with three rows per day (pr / r / po).
- darkpool price-levels numbers arrive as strings.
- darkpool / lit-flow ignore `date` once `older_than` is set, so pagination
  filters by New York trade date and stops when it crosses into the prior day.
- option flow strikes are cross-checked against the OCC symbol and never used
  to place walls (walls come from gex-levels only).
- spot comes from the dark pool NBBO midpoint, not `underlying_price`.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.parse
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from zoneinfo import ZoneInfo

from .client import UWError

NY = ZoneInfo("America/New_York")
PAGE = 500

CORE_LAYERS = [
    "darkpool-levels", "darkpool", "option-trades", "gex-levels",
    "greek-exposure", "short-interest", "short-volume", "short-data",
]

SECTOR_ETF = {
    "Technology": "XLK", "Communication Services": "XLC", "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP", "Energy": "XLE", "Financial Services": "XLF",
    "Healthcare": "XLV", "Industrials": "XLI", "Real Estate": "XLRE",
    "Basic Materials": "XLB", "Utilities": "XLU",
}

SCREENER_FIELDS = [
    "ticker", "date", "sector", "industry_type", "marketcap", "close",
    "one_day_perc", "one_week_perc", "one_month_perc", "three_month_perc",
    "week_52_high", "week_52_low", "atr_14", "relative_volume", "avg30_volume",
    "iv30d", "iv30d_1d", "iv30d_1w", "iv30d_1m", "iv_rank", "iv_rank_1m",
    "iv_percentile_1m", "iv_percentile_1y", "realized_volatility",
    "implied_move_perc", "implied_move_perc_30",  # short_int omitted: returns 0 while interest-float/v2 has data
    "call_open_interest", "put_open_interest", "prev_call_oi", "prev_put_oi",
    "avg_30_day_call_oi", "avg_30_day_put_oi", "call_volume", "put_volume",
    "avg_30_day_call_volume", "avg_30_day_put_volume", "net_call_premium",
    "net_put_premium", "net_premium", "bullish_premium", "bearish_premium",
    "cum_dir_delta", "cum_dir_gamma", "cum_dir_vega", "gex_daily_net_gex",
    "gex_daily_call_gex", "gex_daily_put_gex", "gex_net_change", "gex_perc_change",
    "gex_ratio", "gex_daily_net_delta", "etf_share_flow", "next_earnings_date", "er_time",
]

# Opening / closing auction reports and crosses are not negotiated block prints.
AUCTION_SALE_CONDS = {"nasdaq_official_close_price", "nasdaq_official_opening_price", "cross_trade"}
AUCTION_TRADE_CODES = {"opening_print", "closing_print"}

ROLL_SHAPES = {
    "call_vertical_spread", "put_vertical_spread", "call_diagonal_spread",
    "put_diagonal_spread", "call_calendar", "put_calendar",
}


# --------------------------------------------------------------------------- helpers
def num(x: Any) -> Optional[float]:
    if x is None or x == "":
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def inum(x: Any) -> Optional[int]:
    v = num(x)
    return int(round(v)) if v is not None else None


_TS = re.compile(r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(\.\d+)?\s*(Z|UTC|[+-]\d{2}(?::?\d{2})?)?$")


def parse_ts(s: Any) -> Optional[datetime]:
    if not s:
        return None
    m = _TS.match(str(s).strip())
    if not m:
        return None
    day, clock, frac, tz = m.groups()
    micro = (frac[1:7].ljust(6, "0")) if frac else "000000"
    if tz in (None, "Z", "UTC"):
        off = "+00:00"
    else:
        off = tz if ":" in tz else (tz + ":00" if len(tz) == 3 else tz[:3] + ":" + tz[3:])
    return datetime.fromisoformat(f"{day}T{clock}.{micro}{off}")


def ny_date(s: Any) -> Optional[str]:
    if s and re.match(r"^\d{4}-\d{2}-\d{2}$", str(s)):
        return str(s)
    dt = parse_ts(s)
    return dt.astimezone(NY).date().isoformat() if dt else None


def ny_clock(s: Any) -> Optional[str]:
    dt = parse_ts(s)
    return dt.astimezone(NY).strftime("%H:%M:%S") if dt else None


def is_rth(s: Any) -> Optional[bool]:
    dt = parse_ts(s)
    if not dt:
        return None
    t = dt.astimezone(NY).time()
    return dtime(9, 30) <= t < dtime(16, 0)


_OCC = re.compile(r"^(?P<root>.+?)(?P<ymd>\d{6})(?P<cp>[CP])(?P<k>\d{8})$")


def parse_occ(sym: Any) -> Optional[Dict[str, Any]]:
    m = _OCC.match(str(sym or "").strip())
    if not m:
        return None
    ymd = m.group("ymd")
    return {
        "root": m.group("root"),
        "expiry": f"20{ymd[:2]}-{ymd[2:4]}-{ymd[4:]}",
        "type": "call" if m.group("cp") == "C" else "put",
        "strike": int(m.group("k")) / 1000.0,
    }


def rows_of(body: Any, key: str = "data") -> List[Any]:
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        v = body.get(key)
        if isinstance(v, list):
            return v
    return []


def days_between(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def third_friday(y: int, m: int) -> date:
    first = date(y, m, 1)
    return first + timedelta(days=(4 - first.weekday()) % 7 + 14)


def weekdays_after(d0: date, d1: date) -> int:
    """Weekdays in (d0, d1]."""
    n, d = 0, d0
    while d < d1:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def ny_day_bounds_utc(d: str) -> Tuple[str, str]:
    day = date.fromisoformat(d)
    start = datetime.combine(day, dtime(0, 0), NY).astimezone(timezone.utc)
    end = datetime.combine(day, dtime(23, 59, 59), NY).astimezone(timezone.utc)
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return start.strftime(fmt), end.strftime(fmt)


def _safe_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s)


def request_key(path: str, params: Optional[Dict[str, Any]]) -> str:
    clean = sorted((k, str(v)) for k, v in (params or {}).items() if v is not None)
    return hashlib.sha1(f"{path}?{urllib.parse.urlencode(clean)}".encode()).hexdigest()[:12]


# --------------------------------------------------------------------------- calendar
class Calendar:
    """Trading days taken from SPY regular-session daily candles."""

    def __init__(self, days: List[str]):
        self.days = sorted(set(days))
        if not self.days:
            raise ValueError("empty trading calendar")

    @classmethod
    def from_ohlc(cls, body: Any) -> "Calendar":
        return cls([r["date"] for r in rows_of(body) if r.get("market_time") == "r" and r.get("date")])

    def latest(self) -> str:
        return self.days[-1]

    def resolve(self, d: str) -> str:
        cands = [x for x in self.days if x <= d]
        if not cands:
            raise ValueError(f"{d} is before the calendar start {self.days[0]}")
        return cands[-1]

    def window(self, d: str, n: int) -> List[str]:
        i = self.days.index(self.resolve(d))
        return self.days[max(0, i - n + 1): i + 1]

    def prev(self, d: str, k: int = 1) -> Optional[str]:
        i = self.days.index(self.resolve(d))
        return self.days[i - k] if i - k >= 0 else None


def calendar_flags(d: str) -> Dict[str, Any]:
    day = date.fromisoformat(d)
    month_end = (date(day.year + day.month // 12, day.month % 12 + 1, 1) - timedelta(days=1))
    q_month = ((day.month - 1) // 3 + 1) * 3
    quarter_end = date(day.year + q_month // 12, q_month % 12 + 1, 1) - timedelta(days=1)
    tf = third_friday(day.year, day.month)
    quads = [third_friday(y, m) for y in (day.year - 1, day.year) for m in (3, 6, 9, 12)]
    last_quad = max(q for q in quads if q <= day)
    return {
        "date": d,
        "weekday": day.strftime("%a"),
        "weekdays_to_month_end": weekdays_after(day, month_end),
        "weekdays_to_quarter_end": weekdays_after(day, quarter_end),
        "month_end": month_end.isoformat(),
        "quarter_end": quarter_end.isoformat(),
        "monthly_opex": tf.isoformat(),
        "is_monthly_opex": day == tf,
        "last_quad_witching": last_quad.isoformat(),
        "days_since_quad_witching": (day - last_quad).days,
        "is_quad_witching": day == last_quad,
        "note": "weekday counts ignore exchange holidays",
    }


# --------------------------------------------------------------------------- results / context
@dataclass
class LayerResult:
    name: str = ""
    core: bool = False
    ok: bool = False
    as_of: Optional[str] = None
    rows: int = 0
    data: Any = None
    reason: Optional[str] = None
    notes: List[str] = field(default_factory=list)
    extra: str = ""

    def log_line(self) -> str:
        if self.ok:
            line = f"✅ RAN {self.name} as-of {self.as_of} rows={self.rows}"
            return line + (f" {self.extra}" if self.extra else "")
        return f"❌ FAIL {self.name} reason: {self.reason}"

    def to_json(self) -> Dict[str, Any]:
        return {"status": "RAN" if self.ok else "FAIL", "core": self.core, "as_of": self.as_of,
                "rows": self.rows, "extra": self.extra or None, "reason": self.reason,
                "notes": self.notes, "data": self.data}


def FAIL(reason: str, **kw: Any) -> LayerResult:
    return LayerResult(ok=False, reason=reason, **kw)


@dataclass
class Config:
    dp_days: int = 22            # 21-day window + the D-21 snapshot
    gex_days: int = 6
    flow_days: int = 5
    block_shares: int = 10_000
    block_premium: float = 200_000
    flow_min_premium: float = 50_000
    multileg_min_size: int = 50
    max_pages: int = 20
    contract_history: int = 8
    universe_size: int = 35
    use_cache: bool = True


class Ctx:
    """Per-ticker (or market-level) fetch context: raw envelopes + day cache.

    Point-in-time mode (cutoff set): timestamped rows after the cutoff are dropped,
    and end-of-day-only sources use K = the last completed session before D.
    """

    def __init__(self, client, ticker: str, D: str, cal: Calendar, cfg: Config,
                 out_dir: str, cache_dir: str, today_ny: str, cutoff: Optional[datetime] = None):
        self.client, self.T, self.D, self.cal, self.cfg = client, ticker, D, cal, cfg
        self.raw_dir = os.path.join(out_dir, ticker, "raw")
        self.cache_dir = os.path.join(cache_dir, ticker)
        self.today_ny = today_ny
        self.cutoff = cutoff
        self.pit = cutoff is not None
        self.cutoff_iso = cutoff.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if cutoff else None
        self.K = (cal.prev(D) or D) if self.pit else D

    def known(self, ts: Any, lag_seconds: float = 0.0) -> bool:
        """True when a timestamped row (plus lag) is at or before the cutoff."""
        if not self.pit:
            return True
        dt = parse_ts(ts)
        return dt is not None and dt + timedelta(seconds=lag_seconds) <= self.cutoff

    def get(self, raw_name: str, path: str, params: Optional[Dict[str, Any]] = None,
            cache_date: Optional[str] = None) -> Any:
        name = _safe_name(raw_name)
        cache_file = None
        if self.cfg.use_cache and cache_date and cache_date < self.today_ny:
            # key on the exact request (path + params) so different dates / params never share a file
            cache_file = os.path.join(self.cache_dir, f"{name}__{request_key(path, params)}.json")
        resp = self.client.get(path, params, cache_file=cache_file)
        os.makedirs(self.raw_dir, exist_ok=True)
        with open(os.path.join(self.raw_dir, name + ".json"), "w") as fh:
            json.dump(resp.envelope(), fh)
        return resp.body


def run_layer(name: str, core: bool, fn: Callable[..., LayerResult], *args: Any) -> LayerResult:
    try:
        res = fn(*args)
    except UWError as e:
        res = FAIL(str(e))
    except Exception as e:  # parse bugs surface as FAIL, never silently
        res = FAIL(f"{type(e).__name__}: {e}")
    res.name, res.core = name, core
    return res


def paginate_day(ctx: Ctx, raw_prefix: str, path: str, params: Dict[str, Any],
                 key_fn: Callable[[Dict[str, Any]], Any], ts_key: str = "executed_at",
                 page_size: int = PAGE, start: Optional[str] = None) -> Tuple[List[Dict[str, Any]], int, bool]:
    """Walk an `older_than` cursor (starting at the cutoff in point-in-time mode, else at `start`),
    keeping only rows whose New York date is D and that are known at the cutoff."""
    seen: Dict[Any, Dict[str, Any]] = {}
    older, pages = ctx.cutoff_iso or start, 0
    for i in range(ctx.cfg.max_pages):
        p = dict(params, limit=page_size)
        if older:
            p["older_than"] = older
        rows = rows_of(ctx.get(f"{raw_prefix}_p{i + 1}", path, p))
        pages += 1
        new, crossed = 0, False
        for r in rows:
            d = ny_date(r.get(ts_key))
            if d is None or d > ctx.D or not ctx.known(r.get(ts_key)):
                continue
            if d < ctx.D:
                crossed = True
                continue
            k = key_fn(r)
            if k not in seen:
                seen[k] = r
                new += 1
        if len(rows) < page_size or crossed or new == 0:
            return list(seen.values()), pages, False
        older = rows[-1].get(ts_key)
        if not older:
            return list(seen.values()), pages, False
    return list(seen.values()), pages, True


def pit_note(ctx: Ctx, what: str) -> List[str]:
    return [f"point-in-time: {what}"] if ctx.pit else []


# --------------------------------------------------------------------------- L1 darkpool-levels
def _levels(rows: List[Dict[str, Any]]) -> Dict[float, List[float]]:
    out: Dict[float, List[float]] = {}
    for r in rows:
        p = num(r.get("price"))
        if p is None:
            continue
        a = out.setdefault(p, [0.0, 0.0])
        a[0] += num(r.get("dark_pool_volume")) or 0.0
        a[1] += num(r.get("regular_volume")) or 0.0
    return out


def level_stats(levels: Dict[float, List[float]], top_n: int = 8) -> Dict[str, Any]:
    dark = sum(v[0] for v in levels.values())
    reg = sum(v[1] for v in levels.values())
    table = [{"price": p, "dark": v[0], "regular": v[1],
              "dp_pct": (v[0] / (v[0] + v[1])) if (v[0] + v[1]) else None}
             for p, v in sorted(levels.items(), reverse=True)]
    top = sorted(table, key=lambda r: r["dark"], reverse=True)[:top_n]
    w = sum(r["dark"] for r in top)
    return {
        "dark_total": dark,
        "regular_total": reg,
        "dp_pct": dark / (dark + reg) if (dark + reg) else None,
        "centroid_top8": (sum(r["price"] * r["dark"] for r in top) / w) if w else None,
        "dark_vwap_all": (sum(p * v[0] for p, v in levels.items()) / dark) if dark else None,
        "top8": sorted(top, key=lambda r: -r["price"]),
        "levels": table,
    }


def layer_darkpool_levels(ctx: Ctx) -> LayerResult:
    end = ctx.K  # price-levels is a full-day aggregate: in point-in-time mode stop at the last completed session
    days = ctx.cal.window(end, ctx.cfg.dp_days)
    by_day: Dict[str, Dict[float, List[float]]] = {}
    per_day: Dict[str, Any] = {}
    missing: List[str] = []
    for d in days:
        body = ctx.get(f"darkpool_levels_{d}", f"/api/darkpool/{ctx.T}/price-levels", {"date": d}, cache_date=d)
        lv = _levels(rows_of(body))
        if not lv:
            missing.append(d)
            continue
        by_day[d] = lv
        st = level_stats(lv)
        per_day[d] = {
            "as_of": body.get("date") if isinstance(body, dict) else None,
            "n_levels": len(lv),
            "dark_total": st["dark_total"], "regular_total": st["regular_total"], "dp_pct": st["dp_pct"],
            "centroid_top8": st["centroid_top8"], "top8_prices": [r["price"] for r in st["top8"]],
            "levels": [[p, v[0], v[1]] for p, v in sorted(lv.items(), reverse=True)],
        }
    if end not in by_day:
        return FAIL(f"empty payload for {end}")
    windows = {}
    for label, n in (("1D", 1), ("1W", 5), ("1M", 21)):
        wd = days[-n:]
        agg: Dict[float, List[float]] = {}
        for d in wd:
            for p, v in by_day.get(d, {}).items():
                a = agg.setdefault(p, [0.0, 0.0])
                a[0] += v[0]
                a[1] += v[1]
        windows[label] = {"from": wd[0], "to": wd[-1], "days": len(wd),
                          "days_present": sum(1 for d in wd if d in by_day), **level_stats(agg)}
    snapshots = {}
    for label, k in (("end", 0), ("end-5", 5), ("end-21", 21)):
        if len(days) > k and days[-1 - k] in per_day:
            pd_ = per_day[days[-1 - k]]
            snapshots[label] = {"date": days[-1 - k], "dp_pct": pd_["dp_pct"], "dark_total": pd_["dark_total"],
                                "centroid_top8": pd_["centroid_top8"], "top8_prices": pd_["top8_prices"]}
    notes = pit_note(ctx, f"{ctx.D} is still in session at the cutoff; price-levels is a full-day aggregate, "
                          f"so windows end at the last completed session {end}")
    if missing:
        notes.append(f"missing days: {', '.join(missing)}")
    extra = f"days={len(by_day)}/{len(days)}"
    return LayerResult(ok=True, as_of=per_day[end]["as_of"] or end, rows=per_day[end]["n_levels"],
                       extra=extra, notes=notes, data={
                           "window_end": end,
                           "definition": {
                               "dp_pct": "dark_pool_volume / (dark_pool_volume + regular_volume) per UW price bucket",
                               "top8": "8 buckets with the most dark_pool_volume in the window",
                               "centroid_top8": "sum(price * dark) / sum(dark) over top8",
                               "windows": "1D = window_end, 1W = last 5 sessions, 1M = last 21 sessions (bucket volumes summed)",
                               "snapshots": "single sessions: window_end, 5 and 21 sessions earlier",
                           },
                           "windows": windows, "snapshots": snapshots, "per_day": per_day})


# --------------------------------------------------------------------------- L2 darkpool (+ lit blocks)
def _stock_trade(r: Dict[str, Any], cfg: Config) -> Dict[str, Any]:
    size, prem = inum(r.get("size")) or 0, num(r.get("premium")) or 0.0
    b, a = num(r.get("nbbo_bid")), num(r.get("nbbo_ask"))
    rth = is_rth(r.get("executed_at"))
    return {
        "executed_at": r.get("executed_at"), "et": ny_clock(r.get("executed_at")),
        "price": num(r.get("price")), "size": size, "premium": prem,
        "nbbo_bid": b, "nbbo_ask": a, "nbbo_mid": round((a + b) / 2, 4) if (a and b) else None,
        "ext_hours": bool(r.get("ext_hour_sold_codes")) or (rth is False),
        "ext_hour_code": r.get("ext_hour_sold_codes"), "sale_cond": r.get("sale_cond_codes"),
        "trade_code": r.get("trade_code"), "settlement": r.get("trade_settlement"),
        "market_center": r.get("market_center"),
        "auction": (r.get("sale_cond_codes") in AUCTION_SALE_CONDS) or (r.get("trade_code") in AUCTION_TRADE_CODES),
        "by_size": size >= cfg.block_shares, "by_premium": prem >= cfg.block_premium,
    }


def _block_summary(trades: List[Dict[str, Any]], day_volume: Optional[int]) -> Dict[str, Any]:
    """Aggregates exclude auction prints (reported separately under `auction`)."""
    def agg(sel: List[Dict[str, Any]]) -> Dict[str, Any]:
        sh = sum(t["size"] for t in sel)
        return {"count": len(sel), "shares": sh, "premium": sum(t["premium"] for t in sel),
                "pct_of_day_volume": (sh / day_volume) if day_volume else None}
    blocks = [t for t in trades if not t["auction"]]
    cond: Dict[str, int] = defaultdict(int)
    for t in blocks:
        cond[t["sale_cond"] or t["trade_code"] or "regular"] += 1
    return {
        "either": agg(blocks),
        "by_size": agg([t for t in blocks if t["by_size"]]),
        "by_premium": agg([t for t in blocks if t["by_premium"]]),
        "after_hours": agg([t for t in blocks if t["ext_hours"]]),
        "auction": agg([t for t in trades if t["auction"]]),
        "by_condition": dict(cond),
        "largest": sorted(blocks, key=lambda t: -t["premium"])[:15],
    }


def _blocks(ctx: Ctx, prefix: str, path: str, extra: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], int, bool]:
    key = lambda r: r.get("tracking_id") or (r.get("executed_at"), r.get("price"), r.get("size"))
    a, p1, t1 = paginate_day(ctx, f"{prefix}_size", path, dict(extra, date=ctx.D, min_size=ctx.cfg.block_shares), key)
    b, p2, t2 = paginate_day(ctx, f"{prefix}_premium", path, dict(extra, date=ctx.D, min_premium=int(ctx.cfg.block_premium)), key)
    merged = {key(r): r for r in a + b if not r.get("canceled")}
    trades = sorted((_stock_trade(r, ctx.cfg) for r in merged.values()), key=lambda t: t["executed_at"] or "", reverse=True)
    return trades, p1 + p2, t1 or t2


def layer_darkpool(ctx: Ctx) -> LayerResult:
    path = f"/api/darkpool/{ctx.T}"
    params = {"date": ctx.D, "limit": 50, "cancellation_status": "hide_cancelled"}
    if ctx.pit:
        params["older_than"] = ctx.cutoff_iso
    latest = [r for r in rows_of(ctx.get("darkpool_latest", path, params))
              if ny_date(r.get("executed_at")) == ctx.D and ctx.known(r.get("executed_at"))]
    if not latest:
        return FAIL(f"empty payload: no dark pool prints on {ctx.D}" + (" before the cutoff" if ctx.pit else ""))
    spot = None
    for r in latest:
        b, a = num(r.get("nbbo_bid")), num(r.get("nbbo_ask"))
        if b and a and a >= b > 0:
            spot = {"mid": round((a + b) / 2, 4), "bid": b, "ask": a, "as_of": r.get("executed_at"),
                    "print_price": num(r.get("price")), "source": "darkpool NBBO midpoint"}
            break
    day_volume = max((inum(r.get("volume")) or 0) for r in latest) or None
    spot_close = None
    if not ctx.pit and spot and is_rth(spot["as_of"]) is False:  # latest print is extended hours: also record the last RTH midpoint
        close_utc = datetime.combine(date.fromisoformat(ctx.D), dtime(16, 0), NY).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for r in rows_of(ctx.get("darkpool_rth_close", path, {"date": ctx.D, "limit": 20, "older_than": close_utc,
                                                               "cancellation_status": "hide_cancelled"})):
            b, a = num(r.get("nbbo_bid")), num(r.get("nbbo_ask"))
            if ny_date(r.get("executed_at")) == ctx.D and is_rth(r.get("executed_at")) and b and a and a >= b > 0:
                spot_close = {"mid": round((a + b) / 2, 4), "bid": b, "ask": a, "as_of": r.get("executed_at")}
                break
    trades, pages, truncated = _blocks(ctx, "darkpool_blocks", path, {"cancellation_status": "hide_cancelled"})
    notes = pit_note(ctx, "prints and cumulative day volume up to the cutoff")
    notes.append("UW dark pool feed only carries prints with premium >= $100k")
    if truncated:
        notes.append(f"block pagination hit max_pages={ctx.cfg.max_pages}; totals are a lower bound")
    if not trades:
        notes.append("no block prints on D")
    extra = f"blocks={len(trades)}" + (f" spot={spot['mid']}" if spot else " spot=n/a")
    return LayerResult(ok=True, as_of=latest[0].get("executed_at"), rows=len(trades), extra=extra, notes=notes, data={
        "spot": spot, "spot_rth_close": spot_close, "day_volume": day_volume, "pages": pages, "truncated": truncated,
        "block_definition": {"min_shares": ctx.cfg.block_shares, "min_premium": ctx.cfg.block_premium, "rule": "size >= min_shares OR premium >= min_premium"},
        "blocks": _block_summary(trades, day_volume), "block_trades": trades,
    })


def layer_lit_blocks(ctx: Ctx) -> LayerResult:
    path = f"/api/lit-flow/{ctx.T}"
    trades, pages, truncated = _blocks(ctx, "lit_blocks", path, {})
    params = {"date": ctx.D, "limit": 20}
    if ctx.pit:
        params["older_than"] = ctx.cutoff_iso
    probe = [r for r in rows_of(ctx.get("lit_latest", path, params))
             if ny_date(r.get("executed_at")) == ctx.D and ctx.known(r.get("executed_at"))]
    if not probe and not trades:
        return FAIL(f"empty payload: no lit prints on {ctx.D}" + (" before the cutoff" if ctx.pit else ""))
    day_volume = max([inum(r.get("volume")) or 0 for r in probe] or [0]) or None
    notes = pit_note(ctx, "prints up to the cutoff") + ["UW lit feed only carries large prints (not the full lit tape)"]
    if truncated:
        notes.append(f"block pagination hit max_pages={ctx.cfg.max_pages}")
    return LayerResult(ok=True, as_of=(probe[0].get("executed_at") if probe else ctx.D), rows=len(trades),
                       extra=f"blocks={len(trades)}", notes=notes, data={
                           "day_volume": day_volume, "pages": pages, "truncated": truncated,
                           "blocks": _block_summary(trades, day_volume), "block_trades": trades})


# --------------------------------------------------------------------------- L3 option-trades
_SIDE_TAGS = {"ask_side": "ask", "bid_side": "bid", "mid_side": "mid", "no_side": "none"}


def trade_side(r: Dict[str, Any]) -> Tuple[str, str]:
    for t in r.get("tags") or []:
        if t in _SIDE_TAGS:
            return _SIDE_TAGS[t], "tag"
    px, b, a = num(r.get("price")), num(r.get("nbbo_bid")), num(r.get("nbbo_ask"))
    if px is not None and b is not None and a is not None and a >= b:
        mid = (a + b) / 2
        return ("ask" if px > mid else "bid" if px < mid else "mid"), "nbbo"
    return "none", "unknown"


def norm_option_trade(r: Dict[str, Any], D: str) -> Dict[str, Any]:
    occ = parse_occ(r.get("option_chain_id")) or {}
    strike_field = num(r.get("strike"))
    strike_occ = occ.get("strike")
    expiry = r.get("expiry") or occ.get("expiry")
    side, side_src = trade_side(r)
    flags = r.get("report_flags") or []
    code = r.get("upstream_condition_detail")
    vol, oi = inum(r.get("volume")), inum(r.get("open_interest"))
    return {
        "t": r.get("executed_at"), "sym": r.get("option_chain_id"),
        "type": (r.get("option_type") or occ.get("type") or "").lower(),
        "expiry": expiry, "dte": days_between(D, expiry) if expiry else None,
        "strike": strike_occ, "strike_field": strike_field,
        "strike_mismatch": (strike_field is not None and strike_occ is not None and abs(strike_field - strike_occ) > 1e-6),
        "side": side, "side_src": side_src,
        "sentiment": next((t for t in (r.get("tags") or []) if t in ("bullish", "bearish", "neutral")), None),
        "sweep": ("intermarket_sweep" in flags) or code == "isoi",
        "code": code, "report_flags": flags,
        "size": inum(r.get("size")) or 0, "price": num(r.get("price")), "premium": num(r.get("premium")) or 0.0,
        "contract_volume": vol, "open_interest": oi,
        "vol_gt_oi": (vol is not None and oi is not None and vol > oi),
        "iv": num(r.get("implied_volatility")), "delta": num(r.get("delta")),
        "underlying_price_unreliable": num(r.get("underlying_price")),
    }


def flow_aggregates(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    prem: Dict[str, float] = defaultdict(float)
    cnt: Dict[str, int] = defaultdict(int)
    by_contract: Dict[str, Dict[str, Any]] = {}
    for t in trades:
        k = f"{t['type']}_{t['side']}"
        prem[k] += t["premium"]
        cnt[k] += t["size"]
        if t["sweep"]:
            prem[k + "_sweep"] += t["premium"]
            cnt[k + "_sweep"] += t["size"]
        c = by_contract.setdefault(t["sym"], {"sym": t["sym"], "type": t["type"], "strike": t["strike"], "expiry": t["expiry"],
                                               "ask_premium": 0.0, "bid_premium": 0.0, "ask_contracts": 0, "bid_contracts": 0,
                                               "sweeps": 0, "trades": 0, "open_interest": t["open_interest"]})
        c["trades"] += 1
        c["sweeps"] += int(t["sweep"])
        if t["side"] in ("ask", "bid"):
            c[f"{t['side']}_premium"] += t["premium"]
            c[f"{t['side']}_contracts"] += t["size"]
    g = lambda k: prem.get(k, 0.0)
    mism = [t for t in trades if t["strike_mismatch"]]
    return {
        "premium_by_type_side": dict(prem), "contracts_by_type_side": dict(cnt),
        "net_call_premium": g("call_ask") - g("call_bid"),
        "net_put_premium": g("put_ask") - g("put_bid"),
        "bullish_premium": g("call_ask") + g("put_bid"),
        "bearish_premium": g("call_bid") + g("put_ask"),
        "sweep_count": sum(1 for t in trades if t["sweep"]),
        "vol_gt_oi_count": sum(1 for t in trades if t["vol_gt_oi"]),
        "strike_mismatch_count": len(mism),
        "strike_mismatch_examples": [{"sym": t["sym"], "strike_field": t["strike_field"], "strike_occ": t["strike"]} for t in mism[:5]],
        "top_contracts": sorted(by_contract.values(), key=lambda c: -(c["ask_premium"] + c["bid_premium"]))[:40],
    }


def layer_option_trades(ctx: Ctx) -> LayerResult:
    latest = ctx.cal.latest()
    if ctx.D != latest:
        return FAIL(f"option-trades only serves the latest trading day ({latest}); "
                    f"see flow-alerts / flow-per-strike / net-prem-ticks for {ctx.D}")
    key = lambda r: r.get("id") or (r.get("executed_at"), r.get("option_chain_id"), r.get("size"), r.get("price"))
    rows, pages, truncated = paginate_day(ctx, "option_trades", "/api/option-trades",
                                          {"ticker_symbol": ctx.T, "min_premium": int(ctx.cfg.flow_min_premium)}, key)
    notes = pit_note(ctx, "trades up to the cutoff")
    if not rows:
        probe = rows_of(ctx.get("option_trades_probe", "/api/option-trades", {"ticker_symbol": ctx.T, "limit": 1}))
        if not probe:
            return FAIL("empty payload: no option trades for the ticker on the latest day")
        notes.append(f"no trades with premium >= {ctx.cfg.flow_min_premium:,.0f}")
    if truncated:
        notes.append(f"pagination hit max_pages={ctx.cfg.max_pages}; aggregates are a lower bound")
    trades = sorted((norm_option_trade(r, ctx.D) for r in rows), key=lambda t: t["t"] or "", reverse=True)
    agg = flow_aggregates(trades)
    if agg["strike_mismatch_count"]:
        notes.append(f"strike field disagrees with OCC symbol on {agg['strike_mismatch_count']} trades (SHORT_ENGINE §7.1)")
    return LayerResult(ok=True, as_of=(trades[0]["t"] if trades else ctx.D), rows=len(trades),
                       extra=f"premium>={ctx.cfg.flow_min_premium:,.0f} pages={pages}", notes=notes, data={
                           "min_premium": ctx.cfg.flow_min_premium, "truncated": truncated,
                           "aggregates": agg, "trades": trades,
                           "note": "strike = parsed from OCC symbol; walls come from gex-levels only"})


# --------------------------------------------------------------------------- L4 gex-levels
def layer_gex_levels(ctx: Ctx) -> LayerResult:
    end = ctx.K  # levels for D are recomputed through the session: point-in-time uses the prior session's levels
    days = ctx.cal.window(end, ctx.cfg.gex_days)
    series: Dict[str, List[Dict[str, Any]]] = {"vol": [], "oi": []}
    notes = pit_note(ctx, f"{ctx.D} levels are rebuilt through the session (look-ahead); using {end} levels; "
                          "see spot-gex for exposure at the cutoff")
    missing: List[str] = []
    for src in ("vol", "oi"):
        for d in days:
            body = ctx.get(f"gex_levels_{src}_{d}", f"/api/stock/{ctx.T}/gex-levels", {"date": d, "source": src}, cache_date=d)
            data = body.get("data") if isinstance(body, dict) else None
            if not isinstance(data, dict) or all(data.get(k) is None for k in ("call_wall", "put_wall", "gamma_flip", "gamma_magnet")):
                missing.append(f"{src}:{d}")
                continue
            if data.get("date") and data["date"] != d:
                notes.append(f"{src}:{d} answered with date {data['date']}")
            series[src].append({
                "requested": d, "date": data.get("date"), "time": data.get("time"), "source": data.get("source") or src,
                "call_wall": num(data.get("call_wall")), "put_wall": num(data.get("put_wall")),
                "gamma_flip": num(data.get("gamma_flip")), "gamma_magnet": num(data.get("gamma_magnet")),
                "nearby_flips": [num(x) for x in (data.get("nearby_flips") or [])],
            })
    latest = next((x for x in series["vol"] if x["requested"] == end), None)
    if latest is None:
        return FAIL(f"empty payload for {end} (source=vol)")
    changes = {}
    for src, rows in series.items():
        if len(rows) >= 2 and rows[-1]["requested"] == end:
            a, b = rows[-2], rows[-1]
            changes[src] = {"from": a["requested"], "to": b["requested"], **{
                k: (b[k] - a[k]) if (a[k] is not None and b[k] is not None) else None
                for k in ("call_wall", "put_wall", "gamma_flip", "gamma_magnet")}}
    if missing:
        notes.append(f"missing: {', '.join(missing)}")
    return LayerResult(ok=True, as_of=f"{latest['date']} {latest['time']}", rows=len(series["vol"]) + len(series["oi"]),
                       extra=f"days={len(days)} sources=vol,oi", notes=notes,
                       data={"levels_date": end, "latest": latest,
                             "latest_oi": next((x for x in series["oi"] if x["requested"] == end), None),
                             "series": series, "day_over_day_change": changes})


# --------------------------------------------------------------------------- L5 greek-exposure
def _net(r: Dict[str, Any], g: str) -> Optional[float]:
    c, p = num(r.get(f"call_{g}")), num(r.get(f"put_{g}"))
    return None if c is None and p is None else (c or 0.0) + (p or 0.0)


def layer_greek_exposure(ctx: Ctx) -> LayerResult:
    rows = rows_of(ctx.get("greek_exposure", f"/api/stock/{ctx.T}/greek-exposure", {"date": ctx.D}))
    if not rows:
        return FAIL("empty payload")
    by_date = {r["date"]: r for r in rows if r.get("date")}
    row = by_date.get(ctx.D)
    if row is None:
        return FAIL(f"no row for {ctx.D} (series max date {max(by_date) if by_date else 'n/a'})")
    today = {"date": ctx.D, **{k: num(row.get(k)) for k in (
        "call_gamma", "put_gamma", "call_delta", "put_delta", "call_vanna", "put_vanna", "call_charm", "put_charm")},
        "net_gamma": _net(row, "gamma"), "net_delta": _net(row, "delta"),
        "net_vanna": _net(row, "vanna"), "net_charm": _net(row, "charm")}
    series = [{"date": d, "net_gamma": _net(r, "gamma"), "net_delta": _net(r, "delta")}
              for d, r in sorted(by_date.items()) if d <= ctx.D][-21:]
    order = "ascending" if rows[0].get("date", "") <= rows[-1].get("date", "") else "descending"
    ng = today["net_gamma"]
    return LayerResult(ok=True, as_of=ctx.D, rows=len(rows), extra=(f"net_gamma={ng:.4f}" if ng is not None else ""),
                       notes=pit_note(ctx, "UW computes daily greek exposure from open interest at the open, so the D row is known at the cutoff"),
                       data={"today": today, "series_21d": series, "payload_order": order,
                             "note": "row picked by date == D (max date), never by position"})


# --------------------------------------------------------------------------- L6-8 shorts
def _latest_on_or_before(rows: List[Dict[str, Any]], key: str, D: str) -> Optional[Dict[str, Any]]:
    cand = [r for r in rows if r.get(key) and (ny_date(r[key]) or "") <= D]
    return max(cand, key=lambda r: str(r[key])) if cand else None


def layer_short_interest(ctx: Ctx) -> LayerResult:
    rows = rows_of(ctx.get("short_interest_v2", f"/api/shorts/{ctx.T}/interest-float/v2"))
    latest = _latest_on_or_before(rows, "market_date", ctx.D)
    if not latest:
        return FAIL("empty payload" if not rows else f"no row on or before {ctx.D}")
    fields = ("market_date", "si_float", "si_float_with_synth_long_pct_of_total_shares", "days_to_cover",
              "short_interest", "total_float", "fee_rate", "rebate_rate", "short_shares_available")
    pick = lambda r: {k: (r.get(k) if k == "market_date" else num(r.get(k))) for k in fields}
    lag = days_between(latest["market_date"], ctx.D)
    series = [pick(r) for r in sorted((r for r in rows if r.get("market_date") and r["market_date"] <= ctx.D),
                                      key=lambda r: r["market_date"], reverse=True)[:6]]
    return LayerResult(ok=True, as_of=latest["market_date"], rows=len(rows), extra=f"lag={lag}d",
                       notes=[f"FINRA short interest lags; {lag} calendar days behind {ctx.D}"]
                       + pit_note(ctx, "latest settlement date on or before D (publication lag not modeled)"),
                       data={"latest": pick(latest), "lag_days": lag, "series": series})


def layer_short_volume(ctx: Ctx) -> LayerResult:
    body = ctx.get("short_volume", f"/api/shorts/{ctx.T}/volume-and-ratio")
    rows = rows_of(body, "si")  # rows live under `si`, not `data`
    bound = ctx.K  # T+1 data: D's file is published after the close, so point-in-time stops at K
    latest = _latest_on_or_before(rows, "market_date", bound)
    if not latest:
        return FAIL("empty payload (`si`)" if not rows else f"no row on or before {bound}")
    pick = lambda r: {"market_date": r.get("market_date"), "short_volume": num(r.get("short_volume")),
                      "total_volume": num(r.get("total_volume")), "short_volume_ratio": num(r.get("short_volume_ratio"))}
    series = [pick(r) for r in sorted((r for r in rows if r.get("market_date") and r["market_date"] <= bound),
                                      key=lambda r: r["market_date"], reverse=True)[:20]]
    return LayerResult(ok=True, as_of=latest["market_date"], rows=len(rows),
                       extra=f"ratio={num(latest.get('short_volume_ratio')):.3f}" if num(latest.get("short_volume_ratio")) is not None else "",
                       notes=pit_note(ctx, f"{ctx.D} short volume is published after the close; latest known session {bound}"),
                       data={"latest": pick(latest), "series_20d": series})


def layer_short_data(ctx: Ctx) -> LayerResult:
    rows = [r for r in rows_of(ctx.get("short_data", f"/api/shorts/{ctx.T}/data")) if ctx.known(r.get("timestamp"))]
    latest = _latest_on_or_before(rows, "timestamp", ctx.D)
    if not latest:
        return FAIL("empty payload" if not rows else f"no row on or before {ctx.D}")
    pick = lambda r: {"timestamp": r.get("timestamp"), "fee_rate": num(r.get("fee_rate")),
                      "rebate_rate": num(r.get("rebate_rate")), "short_shares_available": inum(r.get("short_shares_available"))}
    per_day: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        d = ny_date(r.get("timestamp"))
        if d and d <= ctx.D and (d not in per_day or str(r["timestamp"]) > str(per_day[d]["timestamp"])):
            per_day[d] = r
    series = [dict(pick(per_day[d]), date=d) for d in sorted(per_day, reverse=True)[:20]]
    return LayerResult(ok=True, as_of=latest["timestamp"], rows=len(rows),
                       notes=pit_note(ctx, "latest borrow update at or before the cutoff"),
                       data={"latest": pick(latest), "daily_last_20d": series})


# --------------------------------------------------------------------------- supplemental: price
def layer_ohlc_daily(ctx: Ctx) -> LayerResult:
    end = ctx.K  # D's daily candle is not final at a point-in-time cutoff (see derived.session_so_far)
    rows = [r for r in rows_of(ctx.get("ohlc_1d", f"/api/stock/{ctx.T}/ohlc/1d", {"timeframe": "1Y"}))
            if r.get("market_time") == "r" and r.get("date") and r["date"] <= end]
    rows.sort(key=lambda r: r["date"])  # payload is newest-first, 3 rows/day
    if not rows or rows[-1]["date"] != end:
        return FAIL(f"no regular-session daily candle for {end}")
    bars = [[r["date"], num(r.get("open")), num(r.get("high")), num(r.get("low")), num(r.get("close")), inum(r.get("volume"))] for r in rows]
    closes = [b[4] for b in bars]
    trs = [max(h - l, abs(h - pc), abs(l - pc)) for (_, _, h, l, _, _), pc in zip(bars[1:], closes[:-1])
           if None not in (h, l, pc)]
    ret = lambda k: (closes[-1] / closes[-1 - k] - 1) if len(closes) > k and closes[-1 - k] else None
    derived = {"close": closes[-1], "ret_1d": ret(1), "ret_5d": ret(5), "ret_21d": ret(21),
               "atr14_simple": (sum(trs[-14:]) / 14) if len(trs) >= 14 else None,
               "high_20d": max(b[2] for b in bars[-20:]), "low_20d": min(b[3] for b in bars[-20:])}
    return LayerResult(ok=True, as_of=end, rows=len(bars), notes=pit_note(ctx, f"daily bars through {end}"),
                       data={"bars": bars, "derived": derived, "columns": ["date", "open", "high", "low", "close", "volume"]})


def layer_ohlc_5m(ctx: Ctx) -> LayerResult:
    days = ctx.cal.window(ctx.D, ctx.cfg.flow_days)
    out: Dict[str, List[List[Any]]] = {}
    for d in days:
        rows = [r for r in rows_of(ctx.get(f"ohlc_5m_{d}", f"/api/stock/{ctx.T}/ohlc/5m", {"date": d}, cache_date=d))
                if ny_date(r.get("start_time")) == d]
        if d == ctx.D:  # keep bars that had closed by the cutoff
            rows = [r for r in rows if ctx.known(r.get("end_time")) if r.get("end_time")] if ctx.pit else rows
        rows.sort(key=lambda r: r["start_time"])
        if rows:
            out[d] = [[r["start_time"], num(r.get("open")), num(r.get("high")), num(r.get("low")),
                       num(r.get("close")), inum(r.get("volume")), r.get("market_time")] for r in rows]
    if ctx.D not in out:
        return FAIL(f"empty payload for {ctx.D}" + (" before the cutoff" if ctx.pit else ""))
    last = out[ctx.D][-1][0]
    return LayerResult(ok=True, as_of=last, rows=sum(len(v) for v in out.values()), extra=f"days={len(out)}/{len(days)}",
                       notes=pit_note(ctx, f"{ctx.D} bars closed by the cutoff (last bar starts {last})"),
                       data={"columns": ["start_time", "open", "high", "low", "close", "volume", "market_time"], "days": out})


# --------------------------------------------------------------------------- supplemental: OI
def layer_oi_change(ctx: Ctx) -> LayerResult:
    seen: Dict[str, Dict[str, Any]] = {}
    pages = 0
    for page in range(ctx.cfg.max_pages):
        rows = rows_of(ctx.get(f"oi_change_p{page}", f"/api/stock/{ctx.T}/oi-change", {"date": ctx.D, "limit": PAGE, "page": page}))
        pages += 1
        new = 0
        for r in rows:
            s = r.get("option_symbol")
            if s and s not in seen:
                seen[s] = r
                new += 1
        if len(rows) < PAGE or new == 0:
            break
    if not seen:
        return FAIL("empty payload")
    contracts = []
    for r in seen.values():
        occ = parse_occ(r.get("option_symbol")) or {}
        contracts.append({
            "sym": r.get("option_symbol"), "type": occ.get("type"), "strike": occ.get("strike"), "expiry": occ.get("expiry"),
            "dte": days_between(ctx.D, occ["expiry"]) if occ.get("expiry") else None,
            "curr_date": r.get("curr_date"), "last_date": r.get("last_date"),
            "curr_oi": inum(r.get("curr_oi")), "last_oi": inum(r.get("last_oi")),
            "oi_diff": inum(r.get("oi_diff_plain")), "oi_change_pct": num(r.get("oi_change")),
            "prev_ask_volume": inum(r.get("prev_ask_volume")), "prev_bid_volume": inum(r.get("prev_bid_volume")),
            "prev_mid_volume": inum(r.get("prev_mid_volume")), "prev_multi_leg_volume": inum(r.get("prev_multi_leg_volume")),
            "prev_stock_multi_leg_volume": inum(r.get("prev_stock_multi_leg_volume")),
            "prev_total_premium": num(r.get("prev_total_premium")), "volume": inum(r.get("volume")),
            "trades": inum(r.get("trades")), "days_of_oi_increases": inum(r.get("days_of_oi_increases")),
            "days_of_vol_greater_than_oi": inum(r.get("days_of_vol_greater_than_oi")),
        })
    curr_dates = sorted({c["curr_date"] for c in contracts if c["curr_date"]})
    notes = [] if curr_dates == [ctx.D] else [f"curr_date values {curr_dates} (expected {ctx.D})"]
    notes += pit_note(ctx, "OI is published before the open and volumes are from the prior session, so the D table is known at the cutoff")
    tot: Dict[str, int] = defaultdict(int)
    for c in contracts:
        if c["type"] and c["oi_diff"] is not None:
            tot[f"{c['type']}_oi_diff"] += c["oi_diff"]
    ranked = sorted((c for c in contracts if c["oi_diff"] is not None), key=lambda c: c["oi_diff"])
    return LayerResult(ok=True, as_of=(curr_dates[-1] if curr_dates else ctx.D), rows=len(contracts), extra=f"pages={pages}",
                       notes=notes, data={
                           "note": "curr_oi vs last_oi, with the prior session's ask/bid volume on the same row (SHORT_ENGINE §6.2)",
                           "totals": dict(tot), "top_increase": ranked[::-1][:20], "top_decrease": ranked[:20],
                           "contracts": contracts})


def _norm_contract(r: Dict[str, Any], D: str) -> Dict[str, Any]:
    occ = parse_occ(r.get("option_symbol")) or {}
    vol, oi, poi = inum(r.get("volume")), inum(r.get("open_interest")), inum(r.get("prev_oi"))
    return {
        "sym": r.get("option_symbol"), "type": occ.get("type"), "strike": occ.get("strike"), "expiry": occ.get("expiry"),
        "dte": days_between(D, occ["expiry"]) if occ.get("expiry") else None,
        "volume": vol, "open_interest": oi, "prev_oi": poi,
        "oi_diff": (oi - poi) if (oi is not None and poi is not None) else None,
        "vol_gt_oi": (vol is not None and oi is not None and vol > oi),
        **{k: inum(r.get(k)) for k in ("ask_volume", "bid_volume", "mid_volume", "no_side_volume", "sweep_volume",
                                       "multi_leg_volume", "stock_multi_leg_volume", "floor_volume")},
        "total_premium": num(r.get("total_premium")), "iv": num(r.get("implied_volatility")),
        "delta": num(r.get("delta")), "gamma": num(r.get("gamma")),
        "nbbo_bid": num(r.get("nbbo_bid")), "nbbo_ask": num(r.get("nbbo_ask")), "last_tape_time": r.get("last_tape_time"),
    }


def layer_option_contracts(ctx: Ctx) -> LayerResult:
    latest = ctx.cal.latest()
    if ctx.pit:
        return FAIL("live snapshot with no time filter; not point-in-time (OI side is in oi-change)")
    if ctx.D != latest:
        return FAIL(f"live snapshot only (latest trading day {latest})")
    path = f"/api/stock/{ctx.T}/option-contracts"
    base = {"exclude_zero_vol_chains": "true", "limit": PAGE}
    rows = rows_of(ctx.get("option_contracts", path, base))
    split = False
    if len(rows) >= PAGE:  # endpoint caps at 500 rows: split by expiry
        exps = [r.get("expires") for r in rows_of(ctx.get("expiry_breakdown", f"/api/stock/{ctx.T}/expiry-breakdown", {"date": ctx.D}))
                if r.get("expires") and (inum(r.get("volume")) or 0) > 0]
        by_sym: Dict[str, Dict[str, Any]] = {}
        for e in exps:
            for r in rows_of(ctx.get(f"option_contracts_{e}", path, dict(base, expiry=e))):
                by_sym[r.get("option_symbol")] = r
        rows, split = list(by_sym.values()), True
    if not rows:
        return FAIL("empty payload")
    contracts = sorted((_norm_contract(r, ctx.D) for r in rows), key=lambda c: -(c["volume"] or 0))
    return LayerResult(ok=True, as_of=max((c["last_tape_time"] or "") for c in contracts) or ctx.D, rows=len(contracts),
                       extra=("split_by_expiry" if split else ""), data={"contracts": contracts,
                                                                         "filter": "contracts with volume today"})


def layer_oi_per_strike(ctx: Ctx) -> LayerResult:
    days = ctx.cal.window(ctx.D, 2)
    tables = {}
    for d in days:
        rows = rows_of(ctx.get(f"oi_per_strike_{d}", f"/api/stock/{ctx.T}/oi-per-strike", {"date": d}, cache_date=d))
        tables[d] = {num(r.get("strike")): (inum(r.get("call_oi")) or 0, inum(r.get("put_oi")) or 0) for r in rows if num(r.get("strike")) is not None}
    if not tables.get(ctx.D):
        return FAIL(f"empty payload for {ctx.D}")
    prev = days[0] if len(days) == 2 else None
    pt = tables.get(prev, {}) if prev else {}
    strikes = [[k, c, p, (c - pt[k][0]) if k in pt else None, (p - pt[k][1]) if k in pt else None]
               for k, (c, p) in sorted(tables[ctx.D].items())]
    return LayerResult(ok=True, as_of=ctx.D, rows=len(strikes), extra=f"prev={prev}",
                       data={"columns": ["strike", "call_oi", "put_oi", "call_oi_change", "put_oi_change"],
                             "prev_date": prev, "strikes": strikes})


def layer_options_volume(ctx: Ctx) -> LayerResult:
    end = ctx.K  # daily totals: D's row is end-of-day
    rows = sorted((r for r in rows_of(ctx.get("options_volume", f"/api/stock/{ctx.T}/options-volume", {"limit": 30}))
                   if r.get("date") and r["date"] <= end), key=lambda r: r["date"])
    if not rows or rows[-1]["date"] != end:
        return FAIL(f"no row for {end}")
    keep = lambda r: {k: (v if k == "date" else num(v)) for k, v in r.items()}
    return LayerResult(ok=True, as_of=end, rows=len(rows), notes=pit_note(ctx, f"daily rows through {end}"),
                       data={"series": [keep(r) for r in rows]})


# --------------------------------------------------------------------------- supplemental: IV / tails / activity
def layer_interpolated_iv(ctx: Ctx) -> LayerResult:
    end = ctx.K  # end-of-day values
    rows = rows_of(ctx.get(f"interpolated_iv_{end}", f"/api/stock/{ctx.T}/interpolated-iv", {"date": end}, cache_date=end if ctx.pit else None))
    if not rows:
        return FAIL("empty payload")
    term = [{"days": inum(r.get("days")), "volatility": num(r.get("volatility")),
             "implied_move_perc": num(r.get("implied_move_perc")), "percentile": num(r.get("percentile"))} for r in rows]
    return LayerResult(ok=True, as_of=rows[0].get("date") or end, rows=len(term), notes=pit_note(ctx, f"prior close {end}"),
                       data={"term": term})


def layer_option_sentiment(ctx: Ctx) -> LayerResult:
    end = ctx.K
    body = ctx.get(f"option_sentiment_{end}", f"/api/stock/{ctx.T}/volatility/option-sentiment", {"date": end},
                   cache_date=end if ctx.pit else None)
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict) or not data.get("latest"):
        return FAIL("empty payload")
    hist = [h for h in (data.get("history") or []) if h.get("date") and h["date"] <= end][-30:]
    latest = data["latest"]
    notes = ([] if latest.get("date") == end else [f"latest.date={latest.get('date')}"]) + pit_note(ctx, f"prior close {end}")
    return LayerResult(ok=True, as_of=latest.get("date"), rows=len(hist), notes=notes,
                       data={"latest": latest, "history_30": hist,
                             "note": "AVAR = call vs put IV asymmetry (upside-tail proxy); VWKS = volume-weighted strike vs spot"})


def layer_unusualness(ctx: Ctx) -> LayerResult:
    latest = ctx.cal.latest()
    if ctx.pit:
        return FAIL("endpoint has no date or time parameter; not point-in-time")
    if ctx.D != latest:
        return FAIL(f"endpoint has no date parameter; only the latest day ({latest})")
    body = ctx.get("unusualness", f"/api/stock/{ctx.T}/unusualness")
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict) or not data:
        return FAIL("empty payload")
    notes = [] if data.get("date") == ctx.D else [f"answered for {data.get('date')}"]
    return LayerResult(ok=True, as_of=data.get("date"), rows=1, notes=notes, data=data)


def _bucket_end(D: str, hr_min: Any) -> Optional[datetime]:
    s = str(hr_min or "")
    if not re.match(r"^\d{3,4}$", s):
        return None
    s = s.zfill(4)
    return datetime.combine(date.fromisoformat(D), dtime(int(s[:2]), int(s[2:])), NY)


def layer_options_pulse(ctx: Ctx) -> LayerResult:
    body = ctx.get("options_pulse", f"/api/stock/{ctx.T}/options-pulse", {"date": ctx.D}, cache_date=ctx.D)
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict) or not data.get("latest"):
        return FAIL("empty payload")
    if data["latest"].get("trd_dt") and data["latest"]["trd_dt"] != ctx.D:
        return FAIL(f"payload is for {data['latest']['trd_dt']}, not {ctx.D}")
    intraday = data.get("intraday") or []
    latest = data["latest"]
    if ctx.pit:  # hr_min labels the end of each 10-minute bucket (first bucket 0940)
        intraday = [b for b in intraday if (_bucket_end(ctx.D, b.get("hr_min")) or ctx.cutoff + timedelta(days=1)) <= ctx.cutoff]
        if not intraday:
            return FAIL("no 10-minute bucket had closed by the cutoff (first bucket ends 09:40 ET)")
        latest = intraday[-1]
    return LayerResult(ok=True, as_of=f"{latest.get('trd_dt') or ctx.D} {latest.get('hr_min')}", rows=len(intraday),
                       notes=pit_note(ctx, "buckets closed by the cutoff"),
                       data={"latest": latest, "intraday": intraday,
                             "note": "call_txn / put_txn = opening-buy transaction counts (Nasdaq Options Pulse)"})


def pick_rr_expiry(expiries: List[str], D: str, target: int = 30, lo: int = 14, hi: int = 60) -> Optional[str]:
    """Monthly (third Friday) expiry closest to `target` DTE within [lo, hi]; any expiry if no monthly fits."""
    d0 = date.fromisoformat(D)
    dte = lambda e: (date.fromisoformat(e) - d0).days
    ok = sorted(e for e in set(expiries) if lo <= dte(e) <= hi)
    monthly = [e for e in ok if date.fromisoformat(e) == third_friday(int(e[:4]), int(e[5:7]))]
    pool = monthly or ok
    return min(pool, key=lambda e: (abs(dte(e) - target), e)) if pool else None


def layer_rr_skew(ctx: Ctx, oi_change: Optional[LayerResult]) -> LayerResult:
    exps = [c["expiry"] for c in ((oi_change.data or {}).get("contracts") or []) if c.get("expiry")] if (oi_change and oi_change.ok) else []
    if not exps:  # fall back to the next three monthly expiries
        d0 = date.fromisoformat(ctx.D)
        exps = []
        for i in range(3):
            m = d0.month - 1 + i
            exps.append(third_friday(d0.year + m // 12, m % 12 + 1).isoformat())
    expiry = pick_rr_expiry(exps, ctx.D)
    if not expiry:
        return FAIL("no expiry 14-60 DTE available")
    end = ctx.K  # end-of-day skew
    rows = rows_of(ctx.get("rr_skew", f"/api/stock/{ctx.T}/historical-risk-reversal-skew",
                           {"expiry": expiry, "delta": 25, "date": end}))
    rows = sorted((r for r in rows if r.get("date") and r["date"] <= end), key=lambda r: r["date"])
    if not rows:
        return FAIL(f"empty payload (expiry {expiry})")
    series = [{"date": r["date"], "risk_reversal": num(r.get("risk_reversal"))} for r in rows][-60:]
    return LayerResult(ok=True, as_of=rows[-1]["date"], rows=len(rows), extra=f"expiry={expiry} delta=25",
                       notes=pit_note(ctx, f"series through {end}"),
                       data={"expiry": expiry, "delta": 25, "series": series,
                             "note": "risk_reversal = put IV - call IV at matching |delta|"})


# --------------------------------------------------------------------------- supplemental: flow history / structures
def layer_multi_leg(ctx: Ctx) -> LayerResult:
    days = ctx.cal.window(ctx.D, ctx.cfg.flow_days)
    per_day: Dict[str, Any] = {}
    for d in days:
        start, end = ny_day_bounds_utc(d)
        rows: Dict[str, Dict[str, Any]] = {}
        # `offset` is a page index here (0, 1, 2 ...), not a row offset; UW caps the target at 5,000 rows
        for page in range(5000 // PAGE):
            batch = rows_of(ctx.get(f"multi_leg_{d}_o{page}", "/api/option-trades/multi-leg", {
                "ticker_symbol": ctx.T, "newer_than": start, "older_than": end, "limit": PAGE, "offset": page,
                "min_size": ctx.cfg.multileg_min_size}, cache_date=d))
            for r in batch:
                rows[r.get("id") or json.dumps(r, sort_keys=True)] = r
            if len(batch) < PAGE:
                break
        strategies = []
        for r in rows.values():
            if d == ctx.D and not ctx.known(r.get("executed_at")):
                continue
            strategies.append({
                "id": r.get("id"), "t": r.get("executed_at"), "strategy": r.get("strategy"), "direction": r.get("direction"),
                "net_side": r.get("net_side"), "all_opening_legs": r.get("all_opening_legs"),
                "strikes": [num(x) for x in (r.get("strikes") or [])], "ratios": r.get("ratios"),
                "size": inum(r.get("size")), "net_premium": num(r.get("net_premium")), "total_premium": num(r.get("total_premium")),
                "min_dte": inum(r.get("min_dte")), "max_dte": inum(r.get("max_dte")),
                "diff_types": r.get("diff_types"), "diff_expirations": r.get("diff_expirations"),
                "net_delta": num(r.get("net_delta")), "net_gamma": num(r.get("net_gamma")),
                "underlying_price": num(r.get("underlying_price")),
            })
        summary: Dict[str, Dict[str, float]] = {}
        for s in strategies:
            k = f"{s['strategy']}|{s['net_side']}"
            a = summary.setdefault(k, {"count": 0, "contracts": 0, "total_premium": 0.0})
            a["count"] += 1
            a["contracts"] += s["size"] or 0
            a["total_premium"] += s["total_premium"] or 0.0
        per_day[d] = {"count": len(strategies), "by_strategy_side": summary,
                      "risk_reversals": [s for s in strategies if s["strategy"] == "risk_reversal"],
                      "roll_shapes": [s for s in strategies if s["strategy"] in ROLL_SHAPES],
                      "strategies": strategies}
    return LayerResult(ok=True, as_of=(ctx.cutoff_iso if ctx.pit else ctx.D), rows=sum(v["count"] for v in per_day.values()),
                       extra=f"days={len(days)} min_size={ctx.cfg.multileg_min_size}",
                       notes=pit_note(ctx, f"{ctx.D} strategies executed by the cutoff"),
                       data={"note": "risk_reversal = collar shape; vertical / diagonal / calendar = roll shapes",
                             "per_day": per_day})


FLOW_STRIKE_COLS = ["strike", "call_volume_ask_side", "call_volume_bid_side", "call_premium_ask_side", "call_premium_bid_side",
                    "put_volume_ask_side", "put_volume_bid_side", "put_premium_ask_side", "put_premium_bid_side",
                    "call_volume", "put_volume", "call_premium", "put_premium"]


def layer_flow_per_strike(ctx: Ctx) -> LayerResult:
    days = ctx.cal.window(ctx.D, ctx.cfg.flow_days)
    cols = FLOW_STRIKE_COLS
    out: Dict[str, List[List[Any]]] = {}
    partial = None
    for d in days:
        if ctx.pit and d == ctx.D:
            # flow-per-strike-intraday only carries the day's top strikes (~8), so D up to the cutoff is kept apart
            rows = [r for r in rows_of(ctx.get(f"flow_per_strike_intraday_{d}", f"/api/stock/{ctx.T}/flow-per-strike-intraday",
                                               {"date": d}, cache_date=d)) if ctx.known(r.get("timestamp"))]
            agg: Dict[float, List[float]] = {}
            for r in rows:
                k = num(r.get("strike"))
                if k is None:
                    continue
                a = agg.setdefault(k, [0.0] * (len(cols) - 1))
                for i, c in enumerate(cols[1:]):
                    a[i] += num(r.get(c)) or 0.0
            partial = {"date": d, "until": ctx.cutoff_iso, "strikes": [[k] + v for k, v in sorted(agg.items())],
                       "coverage": "subset: UW's intraday per-strike feed only covers the day's top strikes; "
                                   "complete per-minute totals are in net-prem-ticks"}
            continue
        body = ctx.get(f"flow_per_strike_{d}", f"/api/stock/{ctx.T}/flow-per-strike", {"date": d}, cache_date=d)
        rows = rows_of(body)  # bare list
        rows = [r for r in rows if (r.get("date") or d) == d]
        if rows:
            out[d] = sorted(([num(r.get(c)) for c in cols] for r in rows), key=lambda x: x[0] or 0)
    last = ctx.K
    if last not in out:
        return FAIL(f"empty payload for {last}")
    extra = f"days={len(out)}/{len(days) - (1 if ctx.pit else 0)}"
    if partial is not None:
        extra += f" D-partial strikes={len(partial['strikes'])}"
    notes = pit_note(ctx, f"complete days through {last}; {ctx.D} up to the cutoff is a top-strikes subset in d_partial") if ctx.pit else []
    return LayerResult(ok=True, as_of=last, rows=len(out[last]), extra=extra, notes=notes,
                       data={"columns": cols, "days": out, "d_partial": partial})


def layer_net_prem_ticks(ctx: Ctx) -> LayerResult:
    raw = rows_of(ctx.get("net_prem_ticks", f"/api/stock/{ctx.T}/net-prem-ticks", {"date": ctx.D}, cache_date=ctx.D))
    rows = [r for r in raw if (r.get("date") or ny_date(r.get("tape_time"))) == ctx.D
            and ctx.known(r.get("tape_time"), lag_seconds=60)]  # tape_time = minute start
    if not rows:
        if raw and not any((r.get("date") or ny_date(r.get("tape_time"))) == ctx.D for r in raw):
            return FAIL(f"payload is not for {ctx.D}")
        return FAIL("empty payload" + (" before the cutoff" if ctx.pit else ""))
    cols = ["tape_time", "net_call_premium", "net_put_premium", "net_call_volume", "net_put_volume", "net_delta",
            "call_volume", "put_volume"]
    ticks = [[r.get("tape_time")] + [num(r.get(c)) for c in cols[1:]] for r in rows]
    ticks.sort(key=lambda x: x[0] or "")
    totals = {c: sum((t[i] or 0.0) for t in ticks) for i, c in enumerate(cols) if i > 0}
    return LayerResult(ok=True, as_of=ticks[-1][0] if ctx.pit else (rows[0].get("date") or ctx.D), rows=len(ticks),
                       notes=pit_note(ctx, "minutes completed by the cutoff"),
                       data={"columns": cols, "ticks": ticks, "day_totals": totals})


def layer_flow_alerts(ctx: Ctx) -> LayerResult:
    """UW rule-based flow alerts (repeated hits, floor, sweeps) on D, up to the cutoff in point-in-time mode."""
    key = lambda r: r.get("id") or (r.get("created_at"), r.get("option_chain"), r.get("total_size"))
    rows, pages, truncated = paginate_day(ctx, "flow_alerts", "/api/option-trades/flow-alerts",
                                          {"ticker_symbol": ctx.T}, key, ts_key="created_at", page_size=200,
                                          start=ny_day_bounds_utc(ctx.D)[1])  # no date param: start at the end of D
    alerts = []
    for r in rows:
        occ = parse_occ(r.get("option_chain")) or {}
        alerts.append({
            "t": r.get("created_at"), "sym": r.get("option_chain"), "type": (r.get("type") or occ.get("type") or "").lower(),
            "strike": occ.get("strike"), "expiry": r.get("expiry") or occ.get("expiry"), "rule": r.get("alert_rule"),
            "total_premium": num(r.get("total_premium")), "ask_premium": num(r.get("total_ask_side_prem")),
            "bid_premium": num(r.get("total_bid_side_prem")), "size": inum(r.get("total_size")),
            "trades": inum(r.get("trade_count")), "volume": inum(r.get("volume")), "open_interest": inum(r.get("open_interest")),
            "volume_oi_ratio": num(r.get("volume_oi_ratio")), "sweep": r.get("has_sweep"), "floor": r.get("has_floor"),
            "multileg": r.get("has_multileg"), "all_opening": r.get("all_opening_trades"), "iv": num(r.get("iv")),
            "underlying_price_unreliable": num(r.get("underlying_price")),
        })
    alerts.sort(key=lambda a: a["t"] or "", reverse=True)
    tot: Dict[str, float] = defaultdict(float)
    for a in alerts:
        tot[f"{a['type']}_ask_premium"] += a["ask_premium"] or 0.0
        tot[f"{a['type']}_bid_premium"] += a["bid_premium"] or 0.0
    return LayerResult(ok=True, as_of=(alerts[0]["t"] if alerts else (ctx.cutoff_iso or ctx.D)), rows=len(alerts),
                       extra=f"pages={pages}", notes=pit_note(ctx, "alerts created by the cutoff") +
                       ([f"pagination hit max_pages={ctx.cfg.max_pages}"] if truncated else []) +
                       ([] if alerts else ["no flow alerts on D" + (" before the cutoff" if ctx.pit else "")]),
                       data={"totals": dict(tot), "sweeps": sum(1 for a in alerts if a["sweep"]),
                             "all_opening": sum(1 for a in alerts if a["all_opening"]), "alerts": alerts,
                             "note": "strike parsed from the OCC symbol"})


def layer_spot_gex(ctx: Ctx) -> LayerResult:
    """Per-minute spot gamma/charm/vanna exposure on D (the intraday counterpart of greek-exposure)."""
    rows = [r for r in rows_of(ctx.get("spot_exposures", f"/api/stock/{ctx.T}/spot-exposures", {"date": ctx.D}, cache_date=ctx.D))
            if ny_date(r.get("time")) == ctx.D and ctx.known(r.get("time"))]
    if not rows:
        return FAIL("empty payload" + (" before the cutoff" if ctx.pit else ""))
    rows.sort(key=lambda r: r.get("time") or "")
    cols = ["time", "price", "gamma_per_one_percent_move_oi", "gamma_per_one_percent_move_vol", "gamma_per_one_percent_move_dir",
            "charm_per_one_percent_move_oi", "vanna_per_one_percent_move_oi"]
    series = [[r.get("time")] + [num(r.get(c)) for c in cols[1:]] for r in rows]
    last = dict(zip(cols, series[-1]))
    return LayerResult(ok=True, as_of=last["time"], rows=len(series),
                       extra=f"gamma_oi={last['gamma_per_one_percent_move_oi']}",
                       notes=pit_note(ctx, "latest exposure snapshot at or before the cutoff"),
                       data={"latest": last, "columns": cols, "series": series})


# --------------------------------------------------------------------------- supplemental: cross-checks
def layer_greek_exposure_strike(ctx: Ctx) -> LayerResult:
    rows = rows_of(ctx.get("greek_exposure_strike", f"/api/stock/{ctx.T}/greek-exposure/strike", {"date": ctx.D}))
    if not rows:
        return FAIL("empty payload")
    strikes = []
    for r in rows:
        k, c, p = num(r.get("strike")), num(r.get("call_gex")), num(r.get("put_gex"))
        if k is not None:
            strikes.append([k, c, p, (c or 0.0) + (p or 0.0)])
    strikes.sort(key=lambda x: x[0])
    return LayerResult(ok=True, as_of=rows[0].get("date") or ctx.D, rows=len(strikes),
                       data={"columns": ["strike", "call_gex", "put_gex", "net_gex"], "strikes": strikes,
                             "note": "open-interest basis; cross-check for gex-levels (vol basis by default)"})


def oi_basis_walls(strikes: List[List[float]], spot: Optional[float],
                   gex_oi: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """UW's wall definition applied to greek-exposure/strike (open-of-day OI greeks) as a cross-check.
    Divergence from gex-levels?source=oi is recorded, not resolved: gex-levels stays the source of walls."""
    if spot is None or not strikes:
        return None
    above = [s for s in strikes if s[0] > spot and s[3] > 0]
    below = [s for s in strikes if s[0] < spot and s[3] > 0]
    out: Dict[str, Any] = {
        "spot": spot,
        "call_wall": max(above, key=lambda s: s[3])[0] if above else None,
        "put_wall": max(below, key=lambda s: s[3])[0] if below else None,
        "gamma_magnet": max(strikes, key=lambda s: abs(s[3]))[0],
        "source": "greek-exposure/strike (OI basis, greeks as of the open)",
    }
    if gex_oi:
        out["vs_gex_levels_oi"] = {k: {"gex_levels": gex_oi.get(k), "strike_table": out[k], "agree": gex_oi.get(k) == out[k]}
                                   for k in ("call_wall", "put_wall", "gamma_magnet")}
    return out


def layer_offlit_levels(ctx: Ctx, bin_size: float = 0.25) -> LayerResult:
    end = ctx.K  # full-day aggregate, like darkpool-levels
    rows = rows_of(ctx.get(f"offlit_price_levels_{end}", f"/api/stock/{ctx.T}/stock-volume-price-levels", {"date": end},
                           cache_date=end if ctx.pit else None))
    if not rows:
        return FAIL("empty payload")
    bins: Dict[float, List[float]] = {}
    for r in rows:
        p = num(r.get("price"))
        if p is None:
            continue
        b = round((p // bin_size) * bin_size, 4)
        a = bins.setdefault(b, [0.0, 0.0])
        a[0] += num(r.get("off_vol")) or 0.0
        a[1] += num(r.get("lit_vol")) or 0.0
    off, lit = sum(v[0] for v in bins.values()), sum(v[1] for v in bins.values())
    table = [[k, v[0], v[1], (v[0] / (v[0] + v[1])) if (v[0] + v[1]) else None] for k, v in sorted(bins.items(), reverse=True)]
    return LayerResult(ok=True, as_of=end, rows=len(rows), extra=f"bins={len(table)}",
                       notes=pit_note(ctx, f"full-day aggregate: last completed session {end}"), data={
        "columns": ["price_bin", "off_vol", "lit_vol", "off_pct"], "bin_size": bin_size, "bins": table,
        "off_total": off, "lit_total": lit, "off_pct": off / (off + lit) if (off + lit) else None,
        "note": "FINRA off-exchange vs Nasdaq lit only (UW); second view on darkpool-levels"})


def layer_contract_history(ctx: Ctx, oi_change: Optional[LayerResult], gex: Optional[LayerResult]) -> LayerResult:
    if not (oi_change and oi_change.ok):
        return FAIL("needs oi-change")
    data = oi_change.data or {}
    live = [c for c in data.get("contracts") or [] if c.get("expiry") and c["expiry"] > ctx.D]  # skip contracts expiring on/before D
    ranked = sorted((c for c in live if c["oi_diff"] is not None), key=lambda c: c["oi_diff"])
    picks: List[str] = []

    def add(sym: Optional[str]) -> None:
        if sym and sym not in picks and len(picks) < ctx.cfg.contract_history:
            picks.append(sym)

    for c in ranked[::-1][:3]:
        add(c["sym"])
    for c in ranked[:2]:
        add(c["sym"])
    walls = (gex.data or {}).get("latest") if (gex and gex.ok) else None
    if walls:
        for kind, typ in (("call_wall", "call"), ("put_wall", "put")):
            k = walls.get(kind)
            cands = [c for c in live if c["type"] == typ and k is not None and c["strike"] == k]
            if cands:
                add(max(cands, key=lambda c: c["curr_oi"] or 0)["sym"])
    if not picks:
        return FAIL("no contracts selected")
    out: Dict[str, Any] = {}
    end = ctx.K  # D's daily row carries end-of-day volume
    for sym in picks:
        rows = rows_of(ctx.get(f"contract_history_{sym}", f"/api/option-contract/{sym}/historic", {"limit": 30}), "chains")
        rows = sorted((r for r in rows if r.get("date") and r["date"] <= end), key=lambda r: r["date"])
        out[sym] = [{"date": r["date"], **{k: num(r.get(k)) for k in (
            "open_interest", "volume", "ask_volume", "bid_volume", "mid_volume", "sweep_volume", "multi_leg_volume",
            "stock_multi_leg_volume", "implied_volatility", "total_premium", "last_price")}} for r in rows]
    got = sum(1 for v in out.values() if v)
    if not got:
        return FAIL("empty payloads (`chains`)")
    return LayerResult(ok=True, as_of=end, rows=sum(len(v) for v in out.values()), extra=f"contracts={got}/{len(picks)}",
                       notes=pit_note(ctx, f"daily rows through {end}; D's opening OI is in oi-change"),
                       data={"selection": "unexpired only: top 3 OI increases, top 2 decreases, largest-OI contract at call_wall / put_wall",
                             "contracts": out})


# --------------------------------------------------------------------------- market level
def screener_subset(row: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    for k in SCREENER_FIELDS:
        if k in row:
            v = row[k]
            out[k] = v if k in ("ticker", "date", "sector", "industry_type", "next_earnings_date", "er_time") else num(v)
    return out


def universe_summary(label: str, rows: List[Dict[str, Any]], D: str) -> Dict[str, Any]:
    items = [{"ticker": r.get("ticker"), "net_gex": num(r.get("gex_daily_net_gex")),
              "gex_net_change": num(r.get("gex_net_change")), "marketcap": num(r.get("marketcap")),
              "date": r.get("date")} for r in rows]
    neg = [i["ticker"] for i in items if i["net_gex"] is not None and i["net_gex"] < 0]
    nul = [i["ticker"] for i in items if i["net_gex"] is None]
    dates = sorted({i["date"] for i in items if i["date"]})
    return {"label": label, "as_of": dates[-1] if dates else None, "dates": dates, "n": len(items),
            "negative": len(neg), "negative_names": neg, "null": len(nul), "null_names": nul,
            "items": items, "note": "net_gex = screener gex_daily_net_gex (= greek-exposure call_gamma + put_gamma)"}
