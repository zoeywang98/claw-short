#!/usr/bin/env python3
"""Daily feature table per watchlist name for the full-rulebook backtest (2026-07-16 .. last close).
Sources: /private/tmp/bt_all/raw (one-request UW history series + per-day vol gex-levels), uw_short_fetch/cache (gex 9/17+, DP levels 8/25+),
/private/tmp/bt_trap/dp_raw (DP levels 7/16–8/24) and the latest scan briefs (DP 10/26, gex 10/26).
Everything is data; rule logic lives in rules.py."""
import json, os, glob, sys, math, collections
sys.path.insert(0, '/Users/yuwang/.openclaw/workspace-claw-short/uw_short_fetch')
from uwsf.layers import level_stats, _levels
from uwsf.watchlist import WATCHLIST, tickers_of
WS = '/Users/yuwang/.openclaw/workspace-claw-short'
RAW = '/private/tmp/bt_all/raw'
WL = tickers_of(WATCHLIST)
GROUP = {T: g for g, names in WATCHLIST.items() for T in tickers_of({g: names})} if isinstance(WATCHLIST, dict) else {}
LAST_BRIEF = sorted(d for d in os.listdir(f'{WS}/analysis_data') if len(d) == 10 and d.startswith('2026-'))[-1]

def body(T, name):
    f = f'{RAW}/{T}/{name}.json'
    if not os.path.exists(f): return None
    b = json.load(open(f))['body']
    return b

def rows(b, key='data'):
    if b is None: return []
    if isinstance(b, dict):
        for k in (key, 'data', 'si'):
            if k in b and isinstance(b[k], list): return b[k]
        return []
    return b

def num(x):
    try: return float(x)
    except (TypeError, ValueError): return None

def daily_ohlc(T):
    out = {}
    for r in rows(body(T, 'ohlc1d')):
        if r.get('market_time') not in (None, 'r'): continue
        d = (r.get('date') or r.get('start_time') or '')[:10]
        out[d] = [num(r['open']), num(r['high']), num(r['low']), num(r['close']), num(r.get('total_volume') or r.get('volume'))]
    return dict(sorted(out.items()))

# ---------- trading calendar from SPY daily bars ----------
SPY = daily_ohlc('SPY')
DAYS = [d for d in SPY if d >= '2026-04-01'] or [d for d in json.load(open('/private/tmp/bt_trap/panel.json'))['days']]
IDX = {d: i for i, d in enumerate(DAYS)}

def dp_by_day(T):
    by = {}
    for f in glob.glob(f'/private/tmp/bt_trap/dp_raw/{T}/*.json'):
        b = json.load(open(f))['body']
        by[os.path.basename(f)[:-5]] = _levels(b.get('data') if isinstance(b, dict) else b)
    for f in glob.glob(f'{WS}/uw_short_fetch/cache/{T}/darkpool_levels_*.json'):
        d = os.path.basename(f).split('_')[2]
        b = json.load(open(f))['body']
        lv = _levels(b.get('data') if isinstance(b, dict) else b)
        if lv: by[d] = lv
    pdd = json.load(open(f'{WS}/analysis_data/{LAST_BRIEF}/{T}.json'))['darkpool_levels']['per_day']
    for d, x in pdd.items():
        if d not in by:
            lv = x['levels']; lv = lv['rows'] if isinstance(lv, dict) else lv
            by[d] = {p: [dk, rg] for p, dk, rg in lv}
    return by

def win_stats(by, i, n):
    wd = DAYS[max(0, i - n + 1): i + 1]
    if len(wd) < n or any(d not in by for d in wd): return None
    agg = {}
    for d in wd:
        for p, v in by[d].items():
            a = agg.setdefault(p, [0.0, 0.0]); a[0] += v[0]; a[1] += v[1]
    s = level_stats(agg)
    return {'c': s['centroid_top8'], 'poc': s['poc'], 'dark': s['dark_total'], 'dp_pct': s['dp_pct'],
            'dark_below_close_share': None, 'levels': agg}

def gex_by_day(T):
    out = {}
    for f in glob.glob(f'{WS}/uw_short_fetch/cache/{T}/gex_levels_vol_*.json'):
        d = os.path.basename(f).split('_')[3]
        b = json.load(open(f))['body']; x = b.get('data') if isinstance(b, dict) and 'data' in b else b
        if isinstance(x, dict): out[d] = x
    for f in glob.glob(f'{RAW}/{T}/gex/*.json'):
        d = os.path.basename(f)[:-5]
        b = json.load(open(f))['body']; x = b.get('data') if isinstance(b, dict) and 'data' in b else b
        if isinstance(x, dict) and x.get('gamma_flip') is not None: out[d] = x
    bl = json.load(open(f'{WS}/analysis_data/{LAST_BRIEF}/{T}.json')).get('gex_levels') or {}
    if bl.get('latest') and LAST_BRIEF not in out: out[LAST_BRIEF] = bl['latest']
    return {d: {k: num(x.get(k)) for k in ('gamma_flip', 'call_wall', 'put_wall', 'gamma_magnet')} for d, x in out.items()}

def build(T):
    px = daily_ohlc(T)
    by = dp_by_day(T)
    gx = gex_by_day(T)
    greek = {r['date']: r for r in rows(body(T, 'greek'))}
    iv = {}; rv = {}
    for r in rows(body(T, 'ivrv')):
        if r.get('implied_volatility') is not None: iv[r['date']] = num(r['implied_volatility'])
        if r.get('unshifted_rv_date') and r.get('realized_volatility') is not None: rv[r['unshifted_rv_date']] = num(r['realized_volatility'])
    ivs = sorted(iv.items())
    svr = {r['market_date']: num(r['short_volume_ratio']) for r in rows(body(T, 'svr'), 'data')}
    si_rows = sorted((r for r in rows(body(T, 'si'))), key=lambda r: r['market_date'])
    ov = {r['date']: r for r in rows(body(T, 'optvol'))}
    bor = collections.defaultdict(list)
    for r in rows(body(T, 'borrow')):
        ts = r.get('timestamp') or ''
        bor[ts[:10]].append((ts, num(r.get('fee_rate')), num(r.get('short_shares_available'))))
    borrow = {d: sorted(v)[-1] for d, v in bor.items()}
    earn = sorted({r['report_date'] for r in rows(body(T, 'earn')) if r.get('report_date')})
    feats = []
    for i, d in enumerate(DAYS):
        if d not in px or d < '2026-07-16': continue
        o, h, l, c, vol = px[d]
        f = {'T': T, 'date': d, 'i': i, 'open': o, 'high': h, 'low': l, 'close': c, 'volume': vol, 'group': GROUP.get(T)}
        for n, lab in ((1, '1D'), (2, '2D'), (3, '3D'), (5, '1W'), (21, '1M')):
            s = win_stats(by, i, n)
            f[f'c{lab}'] = s['c'] if s else None
            f[f'dark{lab}'] = s['dark'] if s else None
            f[f'dppct{lab}'] = s['dp_pct'] if s else None
            if lab == '1M' and s:
                lv = s['levels']; dk = sum(v[0] for v in lv.values())
                f['dark1M_below_close_share'] = sum(v[0] for p, v in lv.items() if p <= c) / dk if dk else None
        f['dark_avg1M'] = f['dark1M'] / 21 if f.get('dark1M') else None
        g = gx.get(d) or {}
        f.update({'flip': g.get('gamma_flip'), 'call_wall': g.get('call_wall'), 'put_wall': g.get('put_wall'), 'magnet': g.get('gamma_magnet')})
        gr = greek.get(d)
        if gr:
            f['net_gamma'] = (num(gr.get('call_gamma')) or 0) + (num(gr.get('put_gamma')) or 0)
            f['net_delta'] = (num(gr.get('call_delta')) or 0) + (num(gr.get('put_delta')) or 0)
        f['iv30'] = iv.get(d); f['rv21'] = rv.get(d)
        past = [v for dd, v in ivs if dd <= d][-252:]
        f['iv_rank'] = (f['iv30'] - min(past)) / (max(past) - min(past)) if f['iv30'] is not None and len(past) > 100 and max(past) > min(past) else None
        f['svr'] = svr.get(d)
        # SI: latest FINRA settlement already published by d (settlement + 7 business days)
        pub = [r for r in si_rows if business_add(r['market_date'], 7) <= d]
        if pub:
            r = pub[-1]; f['si_float'] = num(r.get('si_float')); f['dtc'] = num(r.get('days_to_cover')); f['si_date'] = r['market_date']
            f['dtc_hist'] = [num(x.get('days_to_cover')) for x in pub[-3:]]
        x = ov.get(d)
        if x:
            for k in ('call_volume', 'put_volume', 'call_volume_ask_side', 'call_volume_bid_side', 'put_volume_ask_side', 'put_volume_bid_side',
                      'net_call_premium', 'net_put_premium', 'call_premium', 'put_premium', 'avg_30_day_call_volume', 'avg_30_day_put_volume',
                      'call_open_interest', 'put_open_interest', 'bullish_premium', 'bearish_premium'):
                f[k] = num(x.get(k))
        b = borrow.get(d)
        if b: f['fee'] = b[1]; f['avail'] = b[2]
        nxt = [e for e in earn if e >= d]; prv = [e for e in earn if e < d]
        f['next_earn'] = nxt[0] if nxt else None; f['prev_earn'] = prv[-1] if prv else None
        feats.append(f)
    return feats

def business_add(d, n):
    i = 0
    import datetime as dt
    x = dt.date.fromisoformat(d)
    while i < n:
        x += dt.timedelta(days=1)
        if x.weekday() < 5: i += 1
    return x.isoformat()

if __name__ == '__main__':
    out = {'days': DAYS, 'spy': SPY, 'qqq': daily_ohlc('QQQ'), 'smh': daily_ohlc('SMH'),
           'spy_gamma': {r['date']: (num(r.get('call_gamma')) or 0) + (num(r.get('put_gamma')) or 0) for r in rows(body('SPY', 'greek'))},
           'rows': {}}
    for T in WL:
        r = build(T)
        if not r: continue
        out['rows'][T] = r
        miss = {k: sum(1 for x in r if x.get(k) is None) for k in ('c2D', 'c1W', 'flip', 'net_gamma', 'iv30', 'rv21', 'svr', 'si_float', 'call_open_interest', 'fee')}
        print(T, len(r), r[0]['date'], r[-1]['date'], 'missing', {k: v for k, v in miss.items() if v})
    json.dump(out, open('/private/tmp/bt_all/features.json', 'w'))
