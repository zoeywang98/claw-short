"""Daily OHLC (1Y, regular session) for the 23 names + UW darkpool price-levels 2026-04-01..2026-07-15 into
/private/tmp/bt_trap/dp_raw/<T>/<D>.json (same layout as dp_trap/fetch_dp.py). Data only."""
import json, os, sys, concurrent.futures as cf
sys.path.insert(0, '/Users/yuwang/.openclaw/workspace-claw-short/uw_short_fetch')
from uwsf.client import UWClient, load_token
from uwsf.watchlist import WATCHLIST, tickers_of
c = UWClient(load_token(), concurrency=6)
WL = tickers_of(WATCHLIST)
px = {}
for T in WL:
    rows = c.get(f'/api/stock/{T}/ohlc/1d', {'timeframe': '1Y'}).body
    rows = rows.get('data') if isinstance(rows, dict) else rows
    bars = {}
    for x in rows:
        if x.get('market_time') != 'r': continue
        d = (x.get('date') or x.get('start_time') or '')[:10]
        bars[d] = [float(x['open']), float(x['high']), float(x['low']), float(x['close'])]
    px[T] = dict(sorted(bars.items()))
json.dump(px, open('/Users/yuwang/.openclaw/workspace-claw-short/analysis_data/backtest-2026-10-18/olivia_core/prices1y.json', 'w'))
cal = sorted(set(px['LITE']) & set(px['MSFT']))
days = [d for d in cal if '2026-04-01' <= d <= '2026-07-15']
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
