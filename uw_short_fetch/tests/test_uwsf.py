"""Offline tests for the payload quirks. Run: python3 -m unittest discover -s tests"""
import json
import os
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

    def test_universe_summary(self):
        rows = [{"ticker": "A", "gex_daily_net_gex": "-1", "date": D}, {"ticker": "B", "gex_daily_net_gex": "2", "date": D},
                {"ticker": "C", "gex_daily_net_gex": None, "date": D}]
        s = L.universe_summary("x", rows, D)
        self.assertEqual((s["negative"], s["null"], s["n"]), (1, 1, 3))
        self.assertEqual(s["negative_names"], ["A"])

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


if __name__ == "__main__":
    unittest.main()
