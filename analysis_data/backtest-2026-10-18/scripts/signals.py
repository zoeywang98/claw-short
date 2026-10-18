#!/usr/bin/env python3
"""Raw rule inputs recomputed from the briefs the model read (analysis_data/<D>/<T>.json); no model judgment."""
import json, os, re
AD = '/Users/yuwang/.openclaw/workspace-claw-short/analysis_data'
prices = json.load(open('/tmp/bt/prices.json'))
rows = []
for d in sorted(os.listdir(AD)):
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', d) or not ('2026-09-25' <= d <= '2026-10-16'):
        continue
    mb = json.load(open(os.path.join(AD, d, 'market_brief.json'))) if os.path.exists(os.path.join(AD, d, 'market_brief.json')) else {}
    board = (mb.get('watchlist_breaker_board') or {}).get('negative')
    for f in sorted(os.listdir(os.path.join(AD, d))):
        T = f[:-5]
        if not f.endswith('.json') or T == 'market_brief' or T not in prices:
            continue
        b = json.load(open(os.path.join(AD, d, f)))
        w = (b.get('darkpool_levels') or {}).get('windows') or {}
        c = {k: (w.get(k) or {}).get('centroid_top8') for k in ('1D', '2D', '1W', '1M')}
        close = ((b.get('price') or {}).get('derived') or {}).get('close')
        ge = ((b.get('greek_exposure') or {}).get('today') or {})
        gx = b.get('gex_levels') or {}
        vflip = (gx.get('latest') or {}).get('gamma_flip')
        oflip = (gx.get('latest_oi') or {}).get('gamma_flip')
        ivrv = b.get('iv_rv') or {}
        iv = (ivrv.get('iv30') or [[None, None]])[-1][1] if ivrv.get('iv30') else None
        rv = (ivrv.get('rv21_trailing') or [[None, None]])[-1][1] if ivrv.get('rv21_trailing') else None
        sc = b.get('screener') or {}
        ov = (b.get('options_volume_5d') or [{}])[-1] if b.get('options_volume_5d') else {}
        si = (b.get('short_interest') or {}).get('latest') or {}
        sv = (b.get('short_volume') or {}).get('latest') or {}
        sd = (b.get('short_data') or {}).get('latest') or {}
        bp = (((b.get('derived') or {}).get('block_participation') or {}).get('either') or {}).get('pct_total')
        d1 = w.get('1D') or {}
        m1 = w.get('1M') or {}
        avg = (m1.get('dark_total') / m1.get('days_present')) if m1.get('dark_total') and m1.get('days_present') else None
        bars = (b.get('price') or {}).get('last_22_bars') or []
        hi5 = max((x[2] for x in bars[-5:]), default=None); lo5 = min((x[3] for x in bars[-5:]), default=None)
        hi10 = max((x[2] for x in bars[-10:-5]), default=None); lo10 = min((x[3] for x in bars[-10:-5]), default=None)
        r = {'date': d, 'ticker': T, 'close': close, 'board_neg': board,
             'c1D': c['1D'], 'c2D': c['2D'], 'c1W': c['1W'], 'c1M': c['1M'],
             'step_down': bool(c['1M'] and c['1W'] and c['2D'] and c['1M'] > c['1W'] > c['2D']),
             'step_up': bool(c['1M'] and c['1W'] and c['2D'] and c['1M'] < c['1W'] < c['2D']),
             'below_2D': bool(close and c['2D'] and close < c['2D']),
             'below_all3': bool(close and all(c[k] for k in ('1D', '2D', '1W')) and close < min(c['1D'], c['2D'], c['1W'])),
             'above_all3': bool(close and all(c[k] for k in ('1D', '2D', '1W')) and close > max(c['1D'], c['2D'], c['1W'])),
             'net_gamma_neg': (ge.get('net_gamma') or 0) < 0,
             'below_vol_flip': bool(close and vflip and close < vflip),
             'below_oi_flip': bool(close and oflip and close < oflip),
             'near_vol_flip_3pct': bool(close and vflip and abs(close - vflip) / close <= 0.03),
             'rv_gt_iv': bool(iv and rv and rv > iv), 'iv_rank': sc.get('iv_rank'),
             'net_call_prem_neg': (ov.get('net_call_premium') or 0) < 0,
             'net_put_prem_pos': (ov.get('net_put_premium') or 0) > 0,
             'si_ge_10': (si.get('si_float') or 0) >= 0.10, 'dtc_le_2': (si.get('days_to_cover') or 99) <= 2,
             'svr_ge_55': (sv.get('short_volume_ratio') or 0) >= 0.55, 'svr_ge_50': (sv.get('short_volume_ratio') or 0) >= 0.50,
             'borrow_ge_1': (sd.get('fee_rate') or 0) >= 1.0,
             'block_ge_16': (bp or 0) >= 0.16, 'block_le_4': bp is not None and bp <= 0.04,
             'dp_vol_ge_1m': bool(avg and d1.get('dark_total') and d1['dark_total'] >= avg),
             'down_5d_structure': bool(hi5 and hi10 and lo5 and lo10 and hi5 < hi10 and lo5 < lo10),
             'up_5d_structure': bool(hi5 and hi10 and lo5 and lo10 and hi5 > hi10 and lo5 > lo10),
             'ret_5d': ((b.get('price') or {}).get('derived') or {}).get('ret_5d')}
        rows.append(r)
json.dump(rows, open('/tmp/bt/signals.json', 'w'))
import collections
print(len(rows), collections.Counter(r['date'] for r in rows).most_common(3))
print({k: sum(1 for r in rows if r[k] is True) for k in rows[0] if isinstance(rows[0][k], bool)})
