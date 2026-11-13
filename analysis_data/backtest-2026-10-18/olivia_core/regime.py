exec(open('/Users/yuwang/.openclaw/workspace-claw-short/analysis_data/backtest-2026-10-18/olivia_core/bt2.py').read().split("print('样本'")[0])
# regime = equal-weight 23-name trailing 20-day return on the event date; own trend = the name's trailing 20-day return
byT = {T: {r['date']: r['close'] for r in rs} for T, rs in panel.items()}
def trail(T, d, n=20):
    i = idx[d]
    if i < n: return None
    a, b = byT[T].get(days[i - n]), byT[T].get(d)
    return b / a - 1 if a and b else None
reg = {}
for d in days:
    v = [trail(T, d) for T in panel if trail(T, d) is not None]
    reg[d] = sum(v) / len(v) if len(v) >= 20 else None
for name, f in (('名单 20 天平均涨幅 <0（弱势）', lambda r: reg.get(r['date']) is not None and reg[r['date']] < 0),
                ('名单 20 天平均涨幅 ≥0（强势）', lambda r: reg.get(r['date']) is not None and reg[r['date']] >= 0)):
    summ('主口径 · ' + name, [r for r in MAIN if f(r)])
    summ('基准 · ' + name, [r for r in base if f(r)], hs=(3, 5, 10))
print('regime share of days <0:', sum(1 for d in days if reg.get(d) is not None and reg[d] < 0), 'of', sum(1 for d in days if reg.get(d) is not None))
