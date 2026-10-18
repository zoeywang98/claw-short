#!/usr/bin/env python3
"""Open-short state for one ticker (ZZ 2026-10-18 "加"): a ✅ 做空 from an earlier post-close scan stays held until a
close reclaims that entry day's 2D DP centroid (SHORT_ENGINE 失效) or 10 trading days pass, as in the backtest.

Entries are read from logs/<date><suffix>/<T>.reply.json ("**结论**：✅ 做空 · 规则 …", v3 format only); the stop is
analysis_data/<date><suffix>/<T>.json darkpool_levels.windows.2D.centroid_top8; closes come from today's brief
(price.last_22_bars). Returns None when nothing was held going into today.
"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
WS = os.path.dirname(HERE)
MAX_DAYS = 10
ENTRY = re.compile(r"\*\*结论\*\*[:：]\s*✅ 做空 · 规则\s*([0-9、,，\s]+)")


def _entry(day, suffix, T):
    try:
        text = json.load(open(os.path.join(HERE, "logs", f"{day}{suffix}", f"{T}.reply.json"))).get("result") or ""
        brief = json.load(open(os.path.join(WS, "analysis_data", f"{day}{suffix}", f"{T}.json")))
    except (OSError, ValueError):
        return None
    m = ENTRY.search(text)
    stop = (((brief.get("darkpool_levels") or {}).get("windows") or {}).get("2D") or {}).get("centroid_top8")
    if not m or not stop:
        return None
    close = ((brief.get("price") or {}).get("derived") or {}).get("close")
    return {"entry_date": day, "rules": re.sub(r"[\s,，]+", "", m.group(1)).strip("、"), "entry_close": close,
            "stop": stop}


def holding_state(label, T, brief, suffix=""):
    """label = the run's date label (YYYY-MM-DD, YYYY-MM-DD_HHMM, ...); its first 10 chars are today."""
    today = label[:10]
    bars = sorted((b[0], b[4]) for b in ((brief.get("price") or {}).get("last_22_bars") or []) if b and b[0] <= today)
    days = [d for d, _ in bars]
    close = dict(bars)
    if today not in close:
        return None
    window = days[max(0, days.index(today) - MAX_DAYS):days.index(today)]   # earlier sessions only
    active = None
    for d in window:
        if active:
            held = days.index(d) - days.index(active["entry_date"])
            if close[d] > active["stop"] or held >= MAX_DAYS:
                active = None   # exited on d; that day's scan can still open a new one
        if not active:
            active = _entry(d, suffix, T)
    if not active:
        return None
    held = days.index(today) - days.index(active["entry_date"])
    intraday = len(label) > 10 and label[10] == "_"
    if close[today] > active["stop"]:
        status = "盘中已站回失效位（按收盘才算）" if intraday else "今天收盘站回失效位，空单结束"
    elif held >= MAX_DAYS:
        status = f"满 {MAX_DAYS} 个交易日，空单结束"
    else:
        status = "持有中"
    return {**active, "days_held": held, "today_close": close[today], "status": status,
            "rule": f"开仓日 2D 重心 {active['stop']} 是失效位；收盘站回就结束，最多拿 {MAX_DAYS} 个交易日"}


if __name__ == "__main__":
    import sys
    label, T, brief_path = sys.argv[1:4]
    print(json.dumps(holding_state(label, T, json.load(open(brief_path)), sys.argv[4] if len(sys.argv) > 4 else ""),
                     ensure_ascii=False, indent=1))
