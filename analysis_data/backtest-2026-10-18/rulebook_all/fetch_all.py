#!/usr/bin/env python3
"""Data-only backfill for the full-rulebook backtest: one-request history series per ticker + per-day vol gex-levels
for days missing from uw_short_fetch/cache. Output /private/tmp/bt_all/raw/<T>/<name>.json and raw/<T>/gex/<D>.json."""
import json, os, sys, glob, concurrent.futures as cf
sys.path.insert(0, '/Users/yuwang/.openclaw/workspace-claw-short/uw_short_fetch')
from uwsf.client import UWClient, load_token
from uwsf.watchlist import WATCHLIST, tickers_of
WS = '/Users/yuwang/.openclaw/workspace-claw-short'
OUT = '/private/tmp/bt_all/raw'
WL = tickers_of(WATCHLIST)
P = json.load(open('/private/tmp/bt_trap/panel.json'))
days = [d for d in P['days'] if d >= '2026-07-16']
c = UWClient(load_token(), concurrency=6)
SERIES = {'optvol': ('/api/stock/{T}/options-volume', {'limit': 500}), 'greek': ('/api/stock/{T}/greek-exposure', {}),
          'ivrv': ('/api/stock/{T}/volatility/realized', {'timeframe': '1Y'}), 'svr': ('/api/shorts/{T}/volume-and-ratio', {}),
          'si': ('/api/shorts/{T}/interest-float/v2', {}), 'borrow': ('/api/shorts/{T}/data', {}), 'earn': ('/api/earnings/{T}', {}),
          'ohlc4h': ('/api/stock/{T}/ohlc/4h', {'limit': 1000}), 'ohlc1d': ('/api/stock/{T}/ohlc/1d', {'timeframe': '1Y'})}
jobs = []
for T in WL + ['SPY', 'QQQ', 'SMH']:
    for name, (path, params) in SERIES.items():
        if T in ('SPY', 'QQQ', 'SMH') and name not in ('ohlc1d', 'greek', 'ivrv'): continue
        jobs.append(('s', T, name, path.format(T=T), params))
    if T in WL:
        have = {os.path.basename(f).split('_')[3] for f in glob.glob(f'{WS}/uw_short_fetch/cache/{T}/gex_levels_vol_*.json')}
        for d in days:
            if d not in have:
                jobs.append(('g', T, d, f'/api/stock/{T}/gex-levels', {'date': d, 'source': 'vol'}))
def one(j):
    kind, T, name, path, params = j
    f = f'{OUT}/{T}/{name}.json' if kind == 's' else f'{OUT}/{T}/gex/{name}.json'
    if os.path.exists(f): return 'skip'
    os.makedirs(os.path.dirname(f), exist_ok=True)
    try:
        r = c.get(path, params)
        json.dump({'status': r.status, 'body': r.body}, open(f, 'w'))
        return 'ok'
    except Exception as e:
        return f'err {T} {name} {str(e)[:80]}'
with cf.ThreadPoolExecutor(6) as ex:
    res = list(ex.map(one, jobs))
errs = [x for x in res if x.startswith('err')]
print('jobs', len(jobs), 'ok', res.count('ok'), 'skip', res.count('skip'), 'errors', len(errs), errs[:5], 'net', c.network_requests)
