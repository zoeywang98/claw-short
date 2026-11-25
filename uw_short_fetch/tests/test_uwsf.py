"""Offline tests for the payload quirks. Run: python3 -m unittest discover -s tests"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uwsf import layers as L  # noqa: E402
from uwsf.client import Response, UWError, _non_empty, load_token  # noqa: E402

D = "2026-09-25"
DAYS = ["2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24", "2026-09-25"]


class FakeClient:
    def __init__(self, router):
        self.router, self.calls = router, []

    def get(self, path, params=None, cache_file=None):
        self.calls.append((path, dict(params or {}), cache_file))
        return Response(path, 200, self.router(path, dict(params or {})), "t", False, {})


def make_ctx(router, D=D, days=DAYS, today="2026-09-27", cutoff=None, **cfg):
    tmp = tempfile.mkdtemp()
    client = FakeClient(router)
    ctx = L.Ctx(client, "TEST", D, L.Calendar(days), L.Config(**cfg), tmp, os.path.join(tmp, "cache"), today, cutoff)
    return ctx, client


CUT = L.datetime(2026, 9, 25, 9, 35, tzinfo=L.NY)   # 13:35Z


class Helpers(unittest.TestCase):
    def test_numbers_and_timestamps(self):
        self.assertEqual(L.num("1.5"), 1.5)
        self.assertIsNone(L.num(""))
        self.assertEqual(L.inum("12000"), 12000)
        self.assertEqual(L.ny_date("2026-09-25T23:59:26Z"), "2026-09-25")          # 7:59pm ET
        self.assertEqual(L.ny_date("2026-09-26T02:00:00Z"), "2026-09-25")          # 10pm ET
        self.assertEqual(L.ny_date("2023-02-16 00:59:44 UTC"), "2023-02-15")
        self.assertEqual(L.ny_date("2026-09-25T19:59:59.15Z"), "2026-09-25")
        self.assertEqual(L.ny_date("2026-08-31"), "2026-08-31")
        self.assertTrue(L.is_rth("2026-09-25T14:00:00Z"))
        self.assertFalse(L.is_rth("2026-09-25T23:59:26Z"))

    def test_occ(self):
        self.assertEqual(L.parse_occ("NBIS261016C00240000"),
                         {"root": "NBIS", "expiry": "2026-10-16", "type": "call", "strike": 240.0})
        self.assertEqual(L.parse_occ("NBIS1261016P00012500")["root"], "NBIS1")
        self.assertEqual(L.parse_occ("NBIS1261016P00012500")["strike"], 12.5)
        self.assertEqual(L.parse_occ("SPXW261016C05800000")["strike"], 5800.0)
        self.assertIsNone(L.parse_occ("garbage"))

    def test_calendar_flags(self):
        f = L.calendar_flags(D)
        self.assertEqual(f["weekdays_to_month_end"], 3)
        self.assertEqual(f["weekdays_to_quarter_end"], 3)
        self.assertEqual(f["last_quad_witching"], "2026-09-18")
        self.assertEqual(f["days_since_quad_witching"], 7)
        self.assertEqual(L.calendar_flags("2026-12-31")["weekdays_to_quarter_end"], 0)

    def test_calendar_from_newest_first_ohlc(self):
        body = {"data": [{"date": d, "market_time": mt} for d in reversed(DAYS) for mt in ("po", "r", "pr")]}
        cal = L.Calendar.from_ohlc(body)
        self.assertEqual(cal.days, DAYS)
        self.assertEqual(cal.resolve("2026-09-27"), D)          # Sunday -> Friday
        self.assertEqual(cal.window(D, 3), DAYS[-3:])
        self.assertEqual(cal.prev(D), "2026-09-24")

    def test_pick_rr_expiry_prefers_monthly(self):
        exps = ["2026-10-09", "2026-10-16", "2026-10-23", "2026-11-20", "2026-09-26"]
        self.assertEqual(L.pick_rr_expiry(exps, D), "2026-10-16")
        self.assertIsNone(L.pick_rr_expiry(["2026-09-26"], D))

    def test_non_empty(self):
        self.assertFalse(_non_empty({"data": []}))
        self.assertTrue(_non_empty({"si": [1]}))
        self.assertTrue(_non_empty([1]))
        self.assertFalse(_non_empty({"data": None}))

    def test_load_token_from_env_file(self):
        with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as fh:
            fh.write("# c\nexport UW_TEST_TOKEN='abc-123'\n")
        os.environ.pop("UW_TEST_TOKEN", None)
        self.assertEqual(load_token("UW_TEST_TOKEN", fh.name), "abc-123")


class Layers(unittest.TestCase):
    def test_darkpool_levels_strings_windows_centroid(self):
        def router(path, p):
            d = p["date"]
            if d == "2026-09-22":
                return {"data": [], "date": d}
            base = 100.0 + DAYS.index(d)
            return {"date": d, "data": [
                {"price": f"{base:.2f}", "dark_pool_volume": "300", "regular_volume": "100"},
                {"price": f"{base + 0.75:.2f}", "dark_pool_volume": "100", "regular_volume": "100"},
            ]}
        ctx, client = make_ctx(router)
        r = L.layer_darkpool_levels(ctx)
        self.assertTrue(r.ok, r.reason)
        self.assertEqual(r.rows, 2)
        w = r.data["windows"]["1D"]
        self.assertAlmostEqual(w["dp_pct"], 400 / 600)
        self.assertAlmostEqual(w["centroid_top8"], (104 * 300 + 104.75 * 100) / 400)
        self.assertEqual(r.data["windows"]["1W"]["days_present"], 4)
        self.assertEqual((r.data["windows"]["3D"]["from"], r.data["windows"]["3D"]["days_present"]), ("2026-09-23", 3))
        self.assertEqual((r.data["windows"]["2D"]["from"], r.data["windows"]["2D"]["poc"]), ("2026-09-24", 104.0))
        self.assertIn("missing days: 2026-09-22", r.notes)
        # past days pass a cache file, D (< today) too
        self.assertTrue(all(c[2] for c in client.calls))

    def test_darkpool_levels_fails_without_D(self):
        ctx, _ = make_ctx(lambda path, p: {"data": [], "date": p["date"]})
        self.assertFalse(L.layer_darkpool_levels(ctx).ok)

    def test_cache_file_is_unique_per_request(self):
        ctx, client = make_ctx(lambda path, p: {"data": [{"date": p["date"], "tape_time": f"{p['date']}T14:00:00Z"}]})
        ctx.get("same_name", "/api/x", {"date": "2026-09-24"}, cache_date="2026-09-24")
        ctx.get("same_name", "/api/x", {"date": "2026-09-25"}, cache_date="2026-09-25")
        files = [c[2] for c in client.calls]
        self.assertEqual(len(set(files)), 2)
        self.assertNotEqual(L.request_key("/api/x", {"date": "a", "source": "vol"}), L.request_key("/api/x", {"date": "a", "source": "oi"}))

    def test_wrong_date_payload_fails(self):
        ctx, _ = make_ctx(lambda path, p: {"data": [{"date": "2026-09-24", "tape_time": "2026-09-24T14:00:00Z"}]})
        self.assertIn("not for", L.layer_net_prem_ticks(ctx).reason)
        ctx, _ = make_ctx(lambda path, p: {"data": {"latest": {"trd_dt": "2026-09-24", "hr_min": "1620"}, "intraday": []}})
        self.assertFalse(L.layer_options_pulse(ctx).ok)

    def test_cache_only_for_past_days(self):
        ctx, client = make_ctx(lambda path, p: {"data": [{"price": "1", "dark_pool_volume": "1", "regular_volume": "1"}]}, today=D)
        L.layer_darkpool_levels(ctx)
        by_date = {c[1]["date"]: c[2] for c in client.calls}
        self.assertIsNone(by_date[D])
        self.assertIsNotNone(by_date["2026-09-24"])

    def test_greek_exposure_row_by_date_not_position(self):
        rows = [{"date": d, "call_gamma": "10", "put_gamma": str(-i)} for i, d in enumerate(DAYS)]
        ctx, _ = make_ctx(lambda path, p: {"data": rows})
        r = L.layer_greek_exposure(ctx)
        self.assertEqual(r.data["today"]["net_gamma"], 10 - 4)
        self.assertEqual(r.data["payload_order"], "ascending")
        ctx, _ = make_ctx(lambda path, p: {"data": rows[:-1]})
        self.assertFalse(L.layer_greek_exposure(ctx).ok)

    def test_short_volume_si_key_and_max_date(self):
        rows = [{"market_date": "2026-09-26", "short_volume_ratio": "0.9"},
                {"market_date": D, "short_volume_ratio": "0.51", "short_volume": "2", "total_volume": "4"},
                {"market_date": "2026-09-24", "short_volume_ratio": "0.40"}]
        ctx, _ = make_ctx(lambda path, p: {"si": rows})
        r = L.layer_short_volume(ctx)
        self.assertTrue(r.ok)
        self.assertEqual(r.data["latest"]["market_date"], D)
        ctx, _ = make_ctx(lambda path, p: {"data": rows})   # wrong key -> FAIL, not silent
        self.assertFalse(L.layer_short_volume(ctx).ok)

    def test_short_data_latest_timestamp_on_or_before_D(self):
        rows = [{"timestamp": "2026-09-26T14:00:00Z", "fee_rate": "9"},
                {"timestamp": "2026-09-25T15:24:50Z", "fee_rate": "0.4450", "short_shares_available": 7800000},
                {"timestamp": "2026-09-25T11:00:00Z", "fee_rate": "0.5"},
                {"timestamp": "2026-09-24T11:00:00Z", "fee_rate": "0.6"}]
        ctx, _ = make_ctx(lambda path, p: {"data": rows})
        r = L.layer_short_data(ctx)
        self.assertEqual(r.data["latest"]["fee_rate"], 0.445)
        self.assertEqual([x["date"] for x in r.data["daily_last_20d"]], [D, "2026-09-24"])

    def test_short_interest_lag(self):
        ctx, _ = make_ctx(lambda path, p: {"data": [{"market_date": "2026-08-31", "si_float": "0.2"},
                                                    {"market_date": "2026-08-15", "si_float": "0.1"}]})
        r = L.layer_short_interest(ctx)
        self.assertEqual(r.as_of, "2026-08-31")
        self.assertEqual(r.data["lag_days"], 25)

    def test_ohlc_daily_regular_rows_sorted(self):
        rows = [{"date": d, "market_time": mt, "open": "1", "high": "2", "low": "0.5", "close": str(10 + i), "volume": 5}
                for i, d in reversed(list(enumerate(DAYS))) for mt in ("po", "r", "pr")]
        ctx, _ = make_ctx(lambda path, p: {"data": rows})
        r = L.layer_ohlc_daily(ctx)
        self.assertEqual([b[0] for b in r.data["bars"]], DAYS)
        self.assertEqual(r.data["derived"]["close"], 14.0)
        ctx, _ = make_ctx(lambda path, p: {"data": [x for x in rows if x["date"] != D]})
        self.assertFalse(L.layer_ohlc_daily(ctx).ok)

    def test_flow_per_strike_bare_list(self):
        ctx, _ = make_ctx(lambda path, p: [{"date": p["date"], "strike": "240", "call_volume_ask_side": 3}])
        r = L.layer_flow_per_strike(ctx)
        self.assertTrue(r.ok, r.reason)
        self.assertEqual(r.data["days"][D][0][:2], [240.0, 3.0])

    def test_contract_history_chains_key(self):
        oi = L.LayerResult(ok=True, data={"contracts": [{"sym": "TEST261016C00240000", "type": "call", "strike": 240.0,
                                                         "expiry": "2026-10-16", "oi_diff": 50, "curr_oi": 500}]})
        ctx, _ = make_ctx(lambda path, p: {"chains": [{"date": D, "open_interest": 5}, {"date": "2026-09-24", "open_interest": 4}]})
        r = L.layer_contract_history(ctx, oi, None)
        self.assertTrue(r.ok, r.reason)
        self.assertEqual([x["date"] for x in r.data["contracts"]["TEST261016C00240000"]], ["2026-09-24", D])

    def test_gex_levels_dict_payload(self):
        def router(path, p):
            return {"data": {"date": p["date"], "time": "t", "source": p["source"], "call_wall": "250",
                             "put_wall": "237.5", "gamma_flip": "238.04", "gamma_magnet": "240", "nearby_flips": ["238.04"]}}
        ctx, _ = make_ctx(router)
        r = L.layer_gex_levels(ctx)
        self.assertTrue(r.ok, r.reason)
        self.assertEqual(r.data["latest"]["call_wall"], 250.0)
        self.assertEqual(r.data["levels_date"], D)
        self.assertEqual(r.data["day_over_day_change"]["vol"]["call_wall"], 0.0)
        ctx, _ = make_ctx(lambda path, p: {"data": {"date": p["date"], "call_wall": None, "put_wall": None,
                                                    "gamma_flip": None, "gamma_magnet": None}})
        self.assertFalse(L.layer_gex_levels(ctx).ok)

    def test_paginate_stops_when_cursor_crosses_day(self):
        page1 = [{"executed_at": f"2026-09-25T15:{i // 60:02d}:{i % 60:02d}Z", "tracking_id": i} for i in range(500)][::-1]
        page2 = [{"executed_at": "2026-09-25T14:00:00Z", "tracking_id": 999},
                 {"executed_at": "2026-09-24T19:00:00Z", "tracking_id": 1000}]

        def router(path, p):
            return {"data": page2 if "older_than" in p else page1}
        ctx, client = make_ctx(router)
        rows, pages, truncated = L.paginate_day(ctx, "x", "/api/darkpool/TEST", {"date": D}, lambda r: r["tracking_id"])
        self.assertEqual(pages, 2)
        self.assertFalse(truncated)
        self.assertEqual(len(rows), 501)
        self.assertNotIn(1000, {r["tracking_id"] for r in rows})

    def test_option_trade_normalization(self):
        t = L.norm_option_trade({"option_chain_id": "TEST261016C00240000", "strike": "7.2727", "tags": ["bid_side", "bearish"],
                                 "report_flags": ["intermarket_sweep"], "premium": "60000", "size": 10,
                                 "volume": 50, "open_interest": 20, "executed_at": "2026-09-25T15:00:00Z"}, D)
        self.assertEqual((t["side"], t["side_src"]), ("bid", "tag"))
        self.assertTrue(t["sweep"] and t["strike_mismatch"] and t["vol_gt_oi"])
        self.assertEqual(t["strike"], 240.0)
        self.assertEqual(t["dte"], 21)
        side, src = L.trade_side({"price": "1.10", "nbbo_bid": "1.00", "nbbo_ask": "1.10"})
        self.assertEqual((side, src), ("ask", "nbbo"))
        agg = L.flow_aggregates([t])
        self.assertEqual(agg["bearish_premium"], 60000.0)
        self.assertEqual(agg["net_call_premium"], -60000.0)

    def test_option_trades_only_latest_day(self):
        ctx, _ = make_ctx(lambda path, p: {"data": []}, D="2026-09-24")
        r = L.layer_option_trades(ctx)
        self.assertFalse(r.ok)
        self.assertIn("latest trading day", r.reason)

    def test_run_layer_turns_errors_into_fail(self):
        def boom(ctx):
            raise UWError(403, "u", "historic_data_access_missing", "", "too old")
        r = L.run_layer("darkpool-levels", True, boom, None)
        self.assertEqual(r.log_line(), "❌ FAIL darkpool-levels reason: HTTP 403 historic_data_access_missing - too old")
        ok = L.LayerResult(name="short-volume", ok=True, as_of=D, rows=3, extra="ratio=0.510")
        self.assertEqual(ok.log_line(), "✅ RAN short-volume as-of 2026-09-25 rows=3 ratio=0.510")

    def test_flow_iv_premium_weighted_by_side(self):
        mk = lambda side, iv, prem, flags=(), dte=30: {"type": "call", "side": side, "iv": iv, "premium": prem,
                                                      "report_flags": list(flags), "dte": dte}
        f = L.flow_iv([mk("ask", 0.40, 100.0), mk("ask", 0.50, 300.0), mk("bid", 0.30, 400.0),
                       mk("ask", 0.90, 1000.0, ["futures_floor"]), mk("ask", None, 50.0), mk("ask", 12.0, 900.0, dte=0)])
        self.assertAlmostEqual(f["call_ask"]["iv"], (0.40 * 100 + 0.50 * 300) / 400)
        self.assertEqual(f["call_ask"]["prints"], 2)
        self.assertAlmostEqual(f["call_all"]["iv"], (0.40 * 100 + 0.50 * 300 + 0.30 * 400) / 800)
        self.assertIsNone(f["put_ask"]["iv"])

    def test_chain_depth_front_monthly(self):
        mk = lambda k, e, vol=1, bid=1.0, t="2026-09-25T19:00:00Z": {"strike": k, "expiry": e, "volume": vol,
                                                                   "nbbo_bid": bid, "nbbo_ask": 1.1, "last_tape_time": t}
        c = [mk(k, "2026-10-16") for k in range(100, 150)] + [mk(99, "2026-10-16", vol=0), mk(98, "2026-10-16", bid=0),
             mk(97, "2026-10-16", t="2026-09-24T19:00:00Z")] + [mk(k, "2026-10-02") for k in range(100, 110)]
        d = L.chain_depth(c, D, 45)
        self.assertEqual((d["nstrk"], d["thin"], d["front_monthly_expiry"], d["nstrk_front_monthly"]), (50, False, "2026-10-16", 50))
        self.assertEqual(d["nstrk_by_expiry"]["2026-10-02"], 10)
        self.assertTrue(L.chain_depth(c[:40], D, 45)["thin"])

    def test_hv_series(self):
        bars = [[f"2026-09-{i:02d}", None, None, None, 100.0 * (1.01 if i % 2 else 0.99), 1] for i in range(1, 25)]
        hv = L.hv_series(bars, 20)
        self.assertEqual(len(hv), 4)   # 24 closes -> 23 returns -> 4 full 20-return windows
        self.assertEqual(hv[-1][0], "2026-09-24")
        self.assertGreater(hv[-1][1], 0.2)

    def test_iv_rv_rekeys_realized_to_window_end(self):
        rows = [{"date": "2026-08-20", "implied_volatility": "0.40", "price": "10", "realized_volatility": "0.30",
                 "unshifted_rv_date": "2026-09-18"},
                {"date": D, "implied_volatility": "0.35", "price": "11", "realized_volatility": None, "unshifted_rv_date": None},
                {"date": "2026-09-28", "implied_volatility": "0.50", "price": "12"}]
        ctx, _ = make_ctx(lambda path, p: {"data": rows})
        r = L.layer_iv_rv(ctx)
        self.assertTrue(r.ok, r.reason)
        self.assertEqual(r.data["iv30"][-1][:2], [D, 0.35])
        self.assertEqual(r.data["rv21_trailing"], [["2026-09-18", 0.30]])

    def test_oi_basis_walls(self):
        w = L.oi_basis_walls([[230, 0, 0, 5.0], [235, 0, 0, -9.0], [240, 0, 0, 7.0], [245, 0, 0, 3.0]], 238.0,
                             {"call_wall": 245.0, "put_wall": 230.0, "gamma_magnet": 235.0})
        self.assertEqual((w["call_wall"], w["put_wall"], w["gamma_magnet"]), (240, 230, 235))
        self.assertFalse(w["vs_gex_levels_oi"]["call_wall"]["agree"])
        self.assertTrue(w["vs_gex_levels_oi"]["put_wall"]["agree"])

    def test_block_summary_excludes_auction_prints(self):
        cfg = L.Config()
        rows = [{"executed_at": "2026-09-25T20:00:00Z", "size": 456595, "premium": "1", "sale_cond_codes": "nasdaq_official_close_price"},
                {"executed_at": "2026-09-25T20:00:00Z", "size": 8318, "premium": "1", "sale_cond_codes": "cross_trade", "trade_code": "closing_print"},
                {"executed_at": "2026-09-25T15:00:00Z", "size": 12000, "premium": "2000000"}]
        s = L._block_summary([L._stock_trade(r, cfg) for r in rows], 1_000_000)
        self.assertEqual(s["either"]["shares"], 12000)
        self.assertEqual(s["auction"]["shares"], 456595 + 8318)
        self.assertAlmostEqual(s["either"]["pct_of_day_volume"], 0.012)

    def test_contract_history_skips_expired(self):
        oi = L.LayerResult(ok=True, data={"contracts": [
            {"sym": "TEST260925C00250000", "type": "call", "strike": 250.0, "expiry": "2026-09-25", "oi_diff": 900, "curr_oi": 9000},
            {"sym": "TEST261016C00250000", "type": "call", "strike": 250.0, "expiry": "2026-10-16", "oi_diff": 10, "curr_oi": 100}]})
        gex = L.LayerResult(ok=True, data={"latest": {"call_wall": 250.0, "put_wall": None}})
        ctx, client = make_ctx(lambda path, p: {"chains": [{"date": D, "open_interest": 1}]})
        r = L.layer_contract_history(ctx, oi, gex)
        self.assertEqual(list(r.data["contracts"]), ["TEST261016C00250000"])


class Watchlist(unittest.TestCase):
    def test_default_list(self):
        from uwsf import watchlist as W
        all_t = W.tickers_of(W.resolve_groups())
        self.assertEqual(len(all_t), 24)   # AMD added 2026-11-24 (ZZ "amd加列表里")
        self.assertEqual(len(set(all_t)), 24)
        self.assertTrue(all(t == t.upper() for t in all_t))
        self.assertEqual(W.tickers_of(W.resolve_groups("optics,商品ETF")), ["LITE", "COHR", "AAOI", "GLW", "AEHR", "SLV"])
        self.assertEqual(W.group_of("NBIS"), "AI基建/电力")
        with self.assertRaises(SystemExit):
            W.resolve_groups("nope")

    def test_group_gamma(self):
        from uwsf.pipeline import group_gamma
        g = {x["group"]: x for x in group_gamma({"LITE": -1.0, "COHR": 2.0, "AAOI": None, "SLV": 3.0})}
        self.assertEqual((g["optics"]["negative"], g["optics"]["n"], g["optics"]["missing"]), (1, 2, ["AAOI"]))
        self.assertEqual(g["commodity_etf"]["negative"], 0)
        self.assertNotIn("pharma", g)


class PointInTime(unittest.TestCase):
    """--asof: rows after the cutoff are dropped; end-of-day sources use K = prior session."""

    def test_ctx(self):
        ctx, _ = make_ctx(lambda p, q: {}, cutoff=CUT)
        self.assertEqual((ctx.pit, ctx.K, ctx.cutoff_iso), (True, "2026-09-24", "2026-09-25T13:35:00Z"))
        self.assertTrue(ctx.known("2026-09-25T13:35:00Z"))
        self.assertFalse(ctx.known("2026-09-25T13:35:01Z"))
        self.assertFalse(ctx.known("2026-09-25T13:34:30Z", lag_seconds=60))
        full, _ = make_ctx(lambda p, q: {})
        self.assertEqual(full.K, D)
        self.assertTrue(full.known("2099-01-01T00:00:00Z"))

    def test_darkpool_levels_end_at_prior_session(self):
        ctx, client = make_ctx(lambda path, p: {"date": p["date"], "data": [{"price": "10", "dark_pool_volume": "3", "regular_volume": "1"}]}, cutoff=CUT)
        r = L.layer_darkpool_levels(ctx)
        self.assertEqual((r.ok, r.as_of, r.data["window_end"]), (True, "2026-09-24", "2026-09-24"))
        self.assertNotIn(D, [c[1]["date"] for c in client.calls])

    def test_short_layers(self):
        sv = [{"market_date": D, "short_volume_ratio": "0.9"}, {"market_date": "2026-09-24", "short_volume_ratio": "0.4"}]
        ctx, _ = make_ctx(lambda path, p: {"si": sv}, cutoff=CUT)
        self.assertEqual(L.layer_short_volume(ctx).as_of, "2026-09-24")
        sd = [{"timestamp": "2026-09-25T15:24:50Z", "fee_rate": "9"}, {"timestamp": "2026-09-25T12:00:00Z", "fee_rate": "0.5"}]
        ctx, _ = make_ctx(lambda path, p: {"data": sd}, cutoff=CUT)
        self.assertEqual(L.layer_short_data(ctx).data["latest"]["fee_rate"], 0.5)

    def test_intraday_filters(self):
        ticks = [{"tape_time": "2026-09-25T13:33:00Z", "net_call_premium": "1"},
                 {"tape_time": "2026-09-25T13:34:00Z", "net_call_premium": "2"},   # minute ends 13:35 -> kept
                 {"tape_time": "2026-09-25T13:35:00Z", "net_call_premium": "4"}]   # ends 13:36 -> dropped
        ctx, _ = make_ctx(lambda path, p: {"data": ticks}, cutoff=CUT)
        self.assertEqual(L.layer_net_prem_ticks(ctx).data["day_totals"]["net_call_premium"], 3.0)
        pulse = {"data": {"latest": {"hr_min": "1620"}, "intraday": [{"hr_min": "0940", "call_txn": 1}]}}
        ctx, _ = make_ctx(lambda path, p: pulse, cutoff=CUT)
        self.assertFalse(L.layer_options_pulse(ctx).ok)                       # first bucket ends 09:40
        ctx, _ = make_ctx(lambda path, p: pulse, cutoff=L.datetime(2026, 9, 25, 9, 40, tzinfo=L.NY))
        self.assertEqual(L.layer_options_pulse(ctx).data["latest"]["call_txn"], 1)
        spot = {"data": [{"time": "2026-09-25T13:30:00Z", "price": "1"}, {"time": "2026-09-25T13:40:00Z", "price": "2"}]}
        ctx, _ = make_ctx(lambda path, p: spot, cutoff=CUT)
        self.assertEqual(L.layer_spot_gex(ctx).data["latest"]["price"], 1.0)

    def test_ohlc_5m_bars_closed_by_cutoff(self):
        bars = [{"start_time": "2026-09-25T13:25:00Z", "end_time": "2026-09-25T13:30:00Z", "market_time": "pr", "close": "1"},
                {"start_time": "2026-09-25T13:30:00Z", "end_time": "2026-09-25T13:35:00Z", "market_time": "r", "close": "2"},
                {"start_time": "2026-09-25T13:35:00Z", "end_time": "2026-09-25T13:40:00Z", "market_time": "r", "close": "3"}]
        ctx, _ = make_ctx(lambda path, p: {"data": bars if p["date"] == D else []}, cutoff=CUT)
        r = L.layer_ohlc_5m(ctx)
        self.assertEqual([b[4] for b in r.data["days"][D]], [1.0, 2.0])

    def test_bars_4h_split_rth_at_1330(self):
        def row(utc, o, h, l, c, v, mt="r"):
            return [utc, o, h, l, c, v, mt]
        days = {"2026-10-16": [row("2026-10-16T13:25:00Z", 9, 99, 1, 9, 5, "pr"),      # 09:25 ET pre-market: skipped
                               row("2026-10-16T13:30:00Z", 10, 12, 9, 11, 100),       # 09:30 ET -> AM
                               row("2026-10-16T17:25:00Z", 11, 13, 10, 12, 50),       # 13:25 ET -> AM
                               row("2026-10-16T17:30:00Z", 12, 15, 11, 14, 70),       # 13:30 ET -> PM
                               row("2026-10-16T19:55:00Z", 14, 14, 8, 9, 30),         # 15:55 ET -> PM
                               row("2026-10-16T20:00:00Z", 9, 20, 1, 9, 5, "po")]}    # post-market: skipped
        self.assertEqual(L.bars_4h(days), [["2026-10-16", "AM", 10, 13, 9, 12, 150, 2],
                                           ["2026-10-16", "PM", 12, 15, 8, 9, 100, 2]])

    def test_finra_settlement_publication_lag(self):
        self.assertFalse(L.published_by("2026-06-30", "2026-06-30"))   # settled, not yet public
        self.assertTrue(L.published_by("2026-06-15", "2026-06-24"))    # 7 business days later
        self.assertFalse(L.published_by("2026-06-15", "2026-06-23"))

    def test_greek_exposure_strike_keeps_delta(self):
        rows = [{"date": D, "strike": "100", "call_gex": "5", "put_gex": "-7", "call_delta": "300", "put_delta": "-450"}]
        ctx, _ = make_ctx(lambda path, p: {"data": rows})
        r = L.layer_greek_exposure_strike(ctx)
        self.assertEqual(r.data["strikes"], [[100.0, 5.0, -7.0, -2.0, 300.0, -450.0, -150.0]])

    def test_flow_per_strike_rebuilds_D_from_minutes(self):
        def router(path, p):
            if path.endswith("intraday"):
                return {"data": [{"timestamp": "2026-09-25T13:31:00Z", "strike": "240", "call_volume_ask_side": 5},
                                 {"timestamp": "2026-09-25T13:32:00Z", "strike": "240", "call_volume_ask_side": 2},
                                 {"timestamp": "2026-09-25T14:00:00Z", "strike": "240", "call_volume_ask_side": 99}]}
            return [{"date": p["date"], "strike": "240", "call_volume_ask_side": 1}]
        ctx, _ = make_ctx(router, cutoff=CUT)
        r = L.layer_flow_per_strike(ctx)
        self.assertNotIn(D, r.data["days"])                                  # partial subset kept apart
        self.assertEqual(r.data["d_partial"]["strikes"][0][:2], [240.0, 7.0])
        self.assertEqual(r.data["days"]["2026-09-24"][0][:2], [240.0, 1.0])
        self.assertEqual(r.as_of, "2026-09-24")

    def test_multi_leg_drops_D_rows_after_cutoff(self):
        rows = [{"id": "a", "executed_at": "2026-09-25T13:34:00Z", "strategy": "risk_reversal"},
                {"id": "b", "executed_at": "2026-09-25T15:00:00Z", "strategy": "risk_reversal"}]
        ctx, _ = make_ctx(lambda path, p: {"data": rows if p["newer_than"].startswith("2026-09-25") else []}, cutoff=CUT)
        r = L.layer_multi_leg(ctx)
        self.assertEqual([s["id"] for s in r.data["per_day"][D]["strategies"]], ["a"])

    def test_live_only_layers_fail(self):
        ctx, _ = make_ctx(lambda path, p: {"data": [{"x": 1}]}, cutoff=CUT)
        self.assertFalse(L.layer_option_contracts(ctx).ok)
        self.assertFalse(L.layer_unusualness(ctx).ok)


def api_levels(path, p):   # API: strings; D has two buckets, the other days one each
    if p["date"] == D:
        return {"date": D, "data": [{"price": "100.0", "dark_pool_volume": "300", "regular_volume": "100"},
                                    {"price": "100.75", "dark_pool_volume": "100", "regular_volume": "50"}]}
    return {"date": p["date"], "data": [{"price": "99.0", "dark_pool_volume": "10", "regular_volume": "5"}]}


SESSIONS = {"1D": 1, "2D": 2, "3D": 3, "1W": 5, "1M": 21}


def site_rows(label, d=D, extra=0):
    """The site's table for a window ending on D (sum of api_levels over the window), as ints."""
    agg = {}
    for day in DAYS[-SESSIONS[label]:]:
        for r in api_levels("", {"date": day})["data"]:
            a = agg.setdefault(r["price"], [0, 0])
            a[0] += int(r["dark_pool_volume"]); a[1] += int(r["regular_volume"])
    rows = [{"price": str(float(k)), "dark_pool_volume": v[0], "regular_volume": v[1]} for k, v in agg.items()]
    rows[0]["dark_pool_volume"] += extra
    rows.append({"price": "120", "dark_pool_volume": 0, "regular_volume": 0})   # all-zero buckets are ignored
    if label == "1D":   # large-trades Price Group
        return {"date": d, "stock_price_vol": rows, "opt_price_vol": [{"price": "100", "call_volume": 5}]}
    return {"date": d, "data": rows}   # stock Dark Pool page, day_range = sessions - 1


class FakeWeb:
    """Stands in for uwweb.UWWeb. `rounds`: one {label: body | Exception-message str} per paired fetch."""

    def __init__(self, rounds=None, fail=None, d=D):
        self.rounds, self.fail, self.batches = rounds, fail, []
        self.d = d

    def start(self, paths):
        from uwsf.uwweb import WebUnavailable
        self.batches.append(dict(paths))
        if self.fail:
            raise WebUnavailable(self.fail)
        return {"n": len(self.batches), "paths": paths}

    def finish(self, h, timeout=45):
        rnd = (self.rounds[min(h["n"], len(self.rounds)) - 1] if self.rounds else {})
        out = {}
        for lab in h["paths"]:
            b = rnd.get(lab, site_rows(lab, d=self.d))
            out[lab] = {"url": h["paths"][lab], "status": 200, "fetched_at": "t", "error": b if isinstance(b, str) else None,
                        "body": None if isinstance(b, str) else b}
        return out


class DicloakSource(unittest.TestCase):
    """ZZ 2026-11-22: price levels from DICloak (the UW site) and the API; identical -> DICloak's, per window."""

    def setUp(self):
        self._sleep, L.WEB_RETRY_SLEEP = L.WEB_RETRY_SLEEP, 0

    def tearDown(self):
        L.WEB_RETRY_SLEEP = self._sleep

    def run_layer(self, web, today="2026-09-27", cutoff=None):
        ctx, client = make_ctx(api_levels, today=today, cutoff=cutoff)
        ctx.web = web
        return L.layer_darkpool_levels(ctx), ctx

    def test_identical_uses_dicloak_for_every_window(self):
        web = FakeWeb()
        r, ctx = self.run_layer(web)
        self.assertTrue(r.ok, r.reason)
        chk = r.data["source_check"]
        self.assertEqual((chk["used"], chk["match"], chk["attempts"], chk["dicloak"]), ("dicloak", True, 1, "ok"))
        self.assertEqual({k: w["source"] for k, w in r.data["windows"].items()},
                         {k: "dicloak" for k in ("1D", "2D", "3D", "1W", "1M")})
        self.assertEqual(r.data["per_day"][D]["source"], "dicloak")
        self.assertEqual(r.data["per_day"]["2026-09-24"]["source"], "api")
        self.assertEqual(len(web.batches), 1)   # one paired fetch, all five site requests in it
        self.assertEqual(web.batches[0]["1D"], "/api/flow/levels/TEST/volume-price-group")
        self.assertEqual(web.batches[0]["2D"], "/api/flow/dark/price_levels/TEST?day_range=1")
        self.assertEqual(web.batches[0]["1W"], "/api/flow/dark/price_levels/TEST?day_range=4")
        self.assertEqual(web.batches[0]["1M"], "/api/flow/dark/price_levels/TEST?day_range=20")
        self.assertIn(f"src={D}:dicloak(=api:1D/2D/3D/1W/1M)", r.extra)
        self.assertAlmostEqual(r.data["windows"]["1D"]["centroid_top8"], (100 * 300 + 100.75 * 100) / 400)
        self.assertEqual(r.data["windows"]["2D"]["dark_total"], 410)
        self.assertTrue(os.path.exists(os.path.join(ctx.raw_dir, f"darkpool_levels_dicloak_{D}.json")))
        self.assertTrue(os.path.exists(os.path.join(ctx.raw_dir, f"darkpool_levels_{D}.json")))   # the API's too

    def test_one_window_differs_on_finished_day(self):
        web = FakeWeb([{"1W": site_rows("1W", extra=7)}])
        r, _ = self.run_layer(web)                       # today 09-27 > D: one paired fetch
        chk = r.data["source_check"]
        self.assertEqual((chk["used"], chk["match"], chk["attempts"]), ("mixed", False, 1))
        self.assertEqual(r.data["windows"]["1W"]["source"], "api")
        self.assertEqual(r.data["windows"]["2D"]["source"], "dicloak")
        self.assertEqual(r.data["windows"]["1W"]["dark_total"], 440)   # the API's sum, not the site's 447
        self.assertTrue(chk["windows"]["1W"]["compare"]["one_sided"])
        self.assertIn(f"src={D}:dicloak(1D/2D/3D/1M)+api(1W)", r.extra)
        self.assertTrue(any("1W: DICloak != API" in n for n in r.notes))

    def test_day_differs_uses_api_day(self):
        web = FakeWeb([{"1D": site_rows("1D", extra=7)}])
        r, _ = self.run_layer(web)
        self.assertEqual(r.data["per_day"][D]["source"], "api")
        self.assertEqual(r.data["windows"]["1D"]["dark_total"], 400)

    def test_live_day_retries_until_they_agree(self):
        web = FakeWeb([{"1D": site_rows("1D", extra=7), "2D": site_rows("2D", extra=7)}, {}])
        r, _ = self.run_layer(web, today=D)
        chk = r.data["source_check"]
        self.assertEqual((chk["used"], chk["attempts"]), ("dicloak", 2))
        self.assertIn(",try2)", r.extra)
        web = FakeWeb([{"1M": site_rows("1M", extra=7)}])
        r, _ = self.run_layer(web, today=D)
        self.assertEqual((r.data["source_check"]["used"], r.data["source_check"]["attempts"]), ("mixed", L.WEB_TRIES))

    def test_unavailable_other_session_or_error_uses_api(self):
        r, _ = self.run_layer(FakeWeb(fail="no unusualwhales.com tab in any open DICloak profile"))
        chk = r.data["source_check"]
        self.assertEqual((chk["used"], chk["match"]), ("api", None))
        self.assertIn("unavailable: no unusualwhales.com tab", chk["dicloak"])
        self.assertIn(f"src={D}:api", r.extra)
        self.assertTrue(r.ok)
        self.assertTrue(all(w["source"] == "api" for w in r.data["windows"].values()))
        r, _ = self.run_layer(FakeWeb(d="2026-09-28"))
        self.assertIn("latest session is 2026-09-28", r.data["source_check"]["windows"]["1D"]["dicloak"])
        self.assertEqual(r.data["source_check"]["used"], "api")
        web = FakeWeb([{"1M": "HTTP 500 from the site: 'x'"}], d=D)
        r, _ = self.run_layer(web, today=D)
        self.assertEqual((r.data["source_check"]["used"], r.data["source_check"]["attempts"]), ("mixed", 1))  # no retry
        self.assertEqual(r.data["windows"]["1M"]["source"], "api")
        self.assertTrue(any("1M: DICloak HTTP 500" in n for n in r.notes))

    def test_no_web_and_point_in_time_skip_dicloak(self):
        r, _ = self.run_layer(None)
        self.assertIsNone(r.data["source_check"])
        self.assertNotIn("src=", r.extra)
        self.assertTrue(all(w["source"] == "api" for w in r.data["windows"].values()))
        web = FakeWeb()
        r, _ = self.run_layer(web, cutoff=CUT)
        self.assertEqual(web.batches, [])

    def test_compare_levels(self):
        a = {100.0: [300.0, 100.0], 101.0: [0.0, 0.0]}
        self.assertTrue(L.compare_levels(a, {100.0: [300.0, 100.0]})["match"])   # all-zero buckets ignored
        c = L.compare_levels(a, {100.0: [290.0, 100.0], 102.0: [5.0, 0.0]})
        self.assertEqual((c["match"], c["buckets_differ"], c["one_sided"], c["only_dicloak"]), (False, 2, False, [102.0]))


class DicloakAlert(unittest.TestCase):
    """ZZ 2026-11-22 "如果有不一致的，@我提醒": one @ZZ post per fetch run, each (date, ticker, phase) once."""

    def setUp(self):
        self._sleep, L.WEB_RETRY_SLEEP = L.WEB_RETRY_SLEEP, 0
        self.state = os.path.join(tempfile.mkdtemp(), "alerts.json")
        self.sent = []

    def tearDown(self):
        L.WEB_RETRY_SLEEP = self._sleep

    def check(self, web, today="2026-09-27"):
        ctx, _ = make_ctx(api_levels, today=today)
        ctx.web = web
        return L.layer_darkpool_levels(ctx).data["source_check"]

    def notify(self, checks, now):
        from uwsf import dpalert
        return dpalert.notify(checks, D, now, state_file=self.state, sender=self.sent.append)

    def test_alert_once_per_ticker_and_phase(self):
        bad = self.check(FakeWeb([{"1W": site_rows("1W", extra=7), "1M": site_rows("1M", extra=-3)}]))
        good = self.check(FakeWeb())
        down = self.check(FakeWeb(fail="no unusualwhales.com tab"))
        close = L.datetime(2026, 9, 25, 17, 1, tzinfo=L.NY)
        note = self.notify({"AAA": bad, "BBB": good, "CCC": down}, close)
        self.assertEqual(len(self.sent), 1)
        msg = self.sent[0]
        self.assertTrue(msg.startswith("<@862859550104223764> 暗池价位 DICloak 和 API 不一致（09/25 17:01 取数）"))
        self.assertIn("- AAA 1W（截至 09/25）：", msg)
        self.assertIn("- AAA 1M（截至 09/25）：", msg)
        self.assertIn("一边比另一边新", msg)
        self.assertNotIn("BBB", msg)
        self.assertNotIn("CCC", msg)          # unavailable is not a disagreement
        self.assertIn("alerted @ZZ", note)
        self.assertIsNone(self.notify({"AAA": bad}, close))   # same day, same phase: already alerted
        self.assertEqual(len(self.sent), 1)
        self.notify({"AAA": bad}, L.datetime(2026, 9, 25, 11, 30, tzinfo=L.NY))   # 盘中 is a separate phase
        self.assertEqual(len(self.sent), 2)

    def test_failed_post_is_reported_not_raised(self):
        from uwsf import dpalert
        bad = self.check(FakeWeb([{"2D": site_rows("2D", extra=7)}]))

        def boom(text):
            raise subprocess.TimeoutExpired("openclaw", 120)
        note = dpalert.notify({"AAA": bad}, D, L.datetime(2026, 9, 25, 17, 1, tzinfo=L.NY),
                              state_file=self.state, sender=boom)
        self.assertIn("alert failed", note)
        self.assertFalse(os.path.exists(self.state))   # not marked as alerted: the next run tries again


class SiteHistory(unittest.TestCase):
    """ZZ 2026-11-22 "每天跑，保存在本地": single sessions from the site's windows, saved, used for earlier days."""

    def setUp(self):
        self._sleep, L.WEB_RETRY_SLEEP = L.WEB_RETRY_SLEEP, 0
        self.root = tempfile.mkdtemp()

    def tearDown(self):
        L.WEB_RETRY_SLEEP = self._sleep

    def test_singles_from_cumulative_windows(self):
        from uwsf import sitestore as S
        r0 = {100.0: [5.0, 1.0]}
        r1 = {100.0: [8.0, 1.0], 99.0: [2.0, 2.0]}
        r2 = {100.0: [8.0, 4.0], 99.0: [3.0, 2.0]}
        one, bad = S.singles({0: r0, 1: r1, 2: r2}, ["d1", "d2", "d3"])
        self.assertEqual(one["d3"], {100.0: [5.0, 1.0]})
        self.assertEqual(one["d2"], {100.0: [3.0, 0.0], 99.0: [2.0, 2.0]})
        self.assertEqual(one["d1"], {100.0: [0.0, 3.0], 99.0: [1.0, 0.0]})
        self.assertEqual(bad, {})
        one, bad = S.singles({0: r1, 1: r0}, ["d1", "d2"])          # a window smaller than the one before
        self.assertIn("negative", bad["d1"])
        self.assertNotIn("d1", one)

    def test_put_get_and_session_over(self):
        from uwsf import sitestore as S
        self.assertEqual(S.put("TEST", {"2026-09-24": ({99.0: [10.0, 5.0], 98.0: [0.0, 0.0]}, "t", "day_range 1-0")},
                               self.root), ["2026-09-24"])
        self.assertEqual(S.get("TEST", "2026-09-24", self.root), {99.0: [10.0, 5.0]})
        self.assertIsNone(S.get("TEST", "2026-09-23", self.root))
        self.assertEqual(S.put("TEST", {"2026-09-24": ({99.0: [10.0, 5.0]}, "t2", "x")}, self.root), [])   # unchanged
        self.assertFalse(S.session_over(D, L.datetime(2026, 9, 25, 17, 0, tzinfo=L.NY)))
        self.assertTrue(S.session_over(D, L.datetime(2026, 9, 25, 20, 30, tzinfo=L.NY)))

    def save_days(self, extra_on=None):
        from uwsf import sitestore as S
        tables = {}
        for d in DAYS[:-1]:
            lv = L._levels(api_levels("", {"date": d})["data"])
            if d == extra_on:
                lv[99.0][0] += 1
            tables[d] = (lv, "t", "day_range")
        S.put("TEST", tables, self.root)

    def layer(self, web=None, cutoff=None, today="2026-09-27"):
        ctx, _ = make_ctx(api_levels, today=today, cutoff=cutoff)
        ctx.web, ctx.store = web, self.root
        return L.layer_darkpool_levels(ctx)

    def test_earlier_days_from_saved_site_tables(self):
        self.save_days()
        r = self.layer(FakeWeb())
        self.assertEqual([r.data["per_day"][d]["source"] for d in DAYS], ["dicloak"] * 5)
        self.assertTrue(all(w["source"] == "dicloak" for w in r.data["windows"].values()))
        self.assertIn("site_days=4/4", r.extra)
        self.assertTrue(all(x["match"] for x in r.data["source_check"]["days"].values()))

    def test_saved_day_differs_uses_api_and_alerts(self):
        from uwsf import dpalert
        self.save_days(extra_on="2026-09-23")
        r = self.layer(FakeWeb())
        self.assertEqual(r.data["per_day"]["2026-09-23"]["source"], "api")
        self.assertEqual(r.data["windows"]["3D"]["source"], "dicloak")   # the site's own 3D table matched the API sum
        self.assertEqual(r.data["windows"]["2D"]["source"], "dicloak")
        self.assertIn("site_days=3/4", r.extra)
        self.assertTrue(any("2026-09-23 single day: saved DICloak table != API" in n for n in r.notes))
        items = dpalert.mismatches("TEST", r.data["source_check"])
        self.assertEqual([(i["label"], i["date"]) for i in items], [("day", "2026-09-23")])
        self.assertIn("- TEST 09/23 单日：", dpalert.message(items, "11/23 17:01"))

    def test_point_in_time_uses_saved_days_without_the_site(self):
        self.save_days()
        web = FakeWeb()
        r = self.layer(web, cutoff=CUT)   # windows end at 09-24; the site is not asked
        self.assertEqual(web.batches, [])
        self.assertEqual(r.data["windows"]["2D"]["source"], "dicloak")
        self.assertNotIn("src=", r.extra)
        self.assertIn("site_days=", r.extra)


if __name__ == "__main__":
    unittest.main()
