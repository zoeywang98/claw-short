import sys, json
sys.path.insert(0, '/Users/yuwang/.openclaw/workspace-claw-short/uw_short_fetch')
from uwsf.client import UWClient, load_token
from uwsf.watchlist import WATCHLIST, tickers_of
c = UWClient(load_token())
out = {}
for T in tickers_of(WATCHLIST) + ['SPY', 'SMH', 'QQQ']:
    rows = c.get(f'/api/stock/{T}/ohlc/1d', {'timeframe': '3M'}).body
    rows = rows.get('data') if isinstance(rows, dict) else rows
    bars = {}
    for x in rows:
        if x.get('market_time') != 'r':
            continue
        d = (x.get('date') or x.get('start_time') or '')[:10]
        bars[d] = [float(x['open']), float(x['high']), float(x['low']), float(x['close'])]
    out[T] = dict(sorted(bars.items()))
    print(T, len(out[T]), min(out[T]), max(out[T]))
json.dump(out, open('/tmp/bt/prices.json', 'w'))
