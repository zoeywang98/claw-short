#!/usr/bin/env python3
"""Backfill UW darkpool price-levels (one request per ticker-day) for 2026-07-16..2026-08-24 into /private/tmp/bt_trap/dp_raw/<T>/<D>.json. Data only."""
import json, os, sys, concurrent.futures as cf
sys.path.insert(0, '/Users/yuwang/.openclaw/workspace-claw-short/uw_short_fetch')
from uwsf.client import UWClient, load_token
from uwsf.watchlist import WATCHLIST, tickers_of
prices = json.load(open('/Users/yuwang/.openclaw/workspace-claw-short/analysis_data/backtest-2026-10-18/prices.json'))
days = [d for d in sorted(prices['SPY']) if '2026-07-16' <= d <= '2026-08-24']
c = UWClient(load_token(), concurrency=6)
OUT = '/private/tmp/bt_trap/dp_raw'
jobs = [(T, d) for T in tickers_of(WATCHLIST) for d in days]
def one(job):
    T, d = job
    f = f'{OUT}/{T}/{d}.json'
    if os.path.exists(f): return T, d, 'skip'
    r = c.get(f'/api/darkpool/{T}/price-levels', {'date': d})
    os.makedirs(f'{OUT}/{T}', exist_ok=True)
    json.dump({'status': r.status, 'body': r.body, 'usage': r.usage}, open(f, 'w'))
    rows = r.body.get('data') if isinstance(r.body, dict) else r.body
    return T, d, len(rows or [])
with cf.ThreadPoolExecutor(6) as ex:
    res = list(ex.map(one, jobs))
empty = [(T, d) for T, d, n in res if n == 0]
print(len(days), 'days', days[0], days[-1], '| jobs', len(jobs), '| empty', len(empty), empty[:10], '| net req', c.network_requests, '| usage', c.last_usage)
