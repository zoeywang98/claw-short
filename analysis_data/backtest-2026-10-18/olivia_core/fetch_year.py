"""Daily OHLC (1Y, regular session) for the 23 names + UW darkpool price-levels 2026-04-01..2026-07-15 into
/private/tmp/bt_trap/dp_raw/<T>/<D>.json (same layout as dp_trap/fetch_dp.py). Data only."""
import json, os, sys, concurrent.futures as cf
sys.path.insert(0, '/Users/yuwang/.openclaw/workspace-claw-short/uw_short_fetch')
from uwsf.client import UWClient, load_token
from uwsf.watchlist import WATCHLIST, tickers_of
c = UWClient(load_token(), concurrency=6)
WL = tickers_of(WATCHLIST)
px = json.load(open('/Users/yuwang/.openclaw/workspace-claw-short/analysis_data/backtest-2026-10-18/olivia_core/prices1y.json')); SKIP_PX = True
cal = sorted(set(px['LITE']) & set(px['MSFT']))
days = [d for d in cal if '2025-11-12' <= d <= '2026-03-31']
OUT = '/private/tmp/bt_trap/dp_raw'
jobs = [(T, d) for T in WL for d in days]
def one(job):
    T, d = job
    f = f'{OUT}/{T}/{d}.json'
    if os.path.exists(f): return T, d, -1
    r = c.get(f'/api/darkpool/{T}/price-levels', {'date': d})
    os.makedirs(f'{OUT}/{T}', exist_ok=True)
    json.dump({'status': r.status, 'body': r.body}, open(f, 'w'))
    rows = r.body.get('data') if isinstance(r.body, dict) else r.body
    return T, d, len(rows or [])
with cf.ThreadPoolExecutor(6) as ex:
    res = list(ex.map(one, jobs))
empty = [(T, d) for T, d, n in res if n == 0]
print('prices', {T: (min(v), max(v), len(v)) for T, v in list(px.items())[:2]}, '| dp days', len(days), days[0], days[-1], '| jobs', len(jobs), '| empty', len(empty), empty[:8])
