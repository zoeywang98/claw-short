#!/usr/bin/env python3
"""Draw the SHORT_ENGINE §4.2 DP grey-centroid migration chart (1M / 1W / 2D, plus the day's own dark volume as a
fourth "当天新增" card, ZZ 2026-11-12) for one ticker from its brief.

Layout follows the rulebook figure: three cards on one shared price axis, dark-pool volume per price as grey bars
growing leftward from the right edge, an arrow between cards. Data only: bars, centroid_top8, poc, the day's
close and the centroid change between windows. The direction call stays in the analysis text.

Needs matplotlib: the system /usr/bin/python3 has it, the homebrew python3 that run.sh's PATH picks does not.

usage: dp_chart.py --brief analysis_data/<D>/<T>.json --out chart.png [--asof HH:MM]
"""
import argparse
import json
import math
import os
import sys
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager as fm  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle  # noqa: E402

# window, title, sessions; the 1D card = that day's own dark volume (ZZ 2026-11-12 "画图的时候每天新增的暗池也画")
PANELS = [("1M", "长周期", 21), ("1W", "中周期", 5), ("2D", "短周期", 2), ("1D", "当天新增", 1)]
# UW price-levels buckets are about $1 wide and labelled by their lower edge (VTRS "17.0" = 17.00-17.89, plus thin
# X.75 / X.9 slivers; LITE goes to $5 above ~1000), so a bin is never narrower than $1 and takes a bucket by its label
BIN_STEPS = [1, 2, 5, 10, 20, 50, 100, 200, 500]
TICK_STEPS = [0.1, 0.2, 0.25, 0.5, 1, 2, 2.5, 5, 10, 20, 25, 50, 100, 200, 250, 500]
MAX_BINS, MAX_TICKS = 50, 8
BAR_MAX_IN = 0.13   # bar thickness cap (inches) for names with only a handful of bins
TAIL = 0.001   # per window, the outer 0.1% of dark volume on each side may fall outside the drawn range

PAGE, CARD_EDGE = "#ffffff", "#d5d8dc"
INK, INK2, MUTED, GRID = "#0b0b0b", "#52514e", "#898781", "#ecebe7"
BAR_TOP, BAR_REST = "#5f6672", "#c6cad0"
CENTROID, CLOSE, ARROW = "#2a78d6", "#0b0b0b", "#9a9893"
ZONE = "#f0a830"   # optional watch zone band (dpzone charts)


def font(*paths):
    for p in paths:
        if os.path.exists(p):
            return fm.FontProperties(fname=p)
    return fm.FontProperties()


REG = font("/System/Library/Fonts/Hiragino Sans GB.ttc", "/Library/Fonts/Arial Unicode.ttf")
BOLD = font("/System/Library/Fonts/STHeiti Medium.ttc", "/System/Library/Fonts/Hiragino Sans GB.ttc")


def wan(v):
    return f"{v / 1e4:,.0f}万" if v >= 1e7 else f"{v / 1e4:.1f}万" if v >= 1e4 else f"{v:,.0f}"


def md(d):
    return f"{int(d[5:7])}/{d[8:10]}"


def rows(table):
    """per_day levels -> [(price, dark)] whichever column order the brief used."""
    if isinstance(table, dict):
        cols = table.get("columns") or ["price", "dark", "regular"]
        ip, idk = cols.index("price"), cols.index("dark")
        return [(r[ip], r[idk] or 0.0) for r in table.get("rows") or [] if r[ip] is not None]
    return [(r[0], r[1] or 0.0) for r in table or [] if r and r[0] is not None]


def wquantile(items, q):
    tot = sum(v for _, v in items)
    acc = 0.0
    for p, v in items:
        acc += v
        if acc >= q * tot:
            return p
    return items[-1][0]


def nice(span, limit, steps):
    return next((s for s in steps if span / s <= limit), steps[-1])


def load(path):
    b = json.load(open(path))
    dl = b.get("darkpool_levels") or {}
    per_day, wins = dl.get("per_day") or {}, dl.get("windows") or {}
    panels = []
    for key, title, sessions in PANELS:
        w = wins.get(key) or {}
        vol = defaultdict(float)
        if w.get("from") and w.get("to"):
            for d, v in per_day.items():
                if w["from"] <= d <= w["to"]:
                    for p, dark in rows(v.get("levels")):
                        vol[p] += dark
        panels.append(dict(key=key, title=title, sessions=sessions, w=w, vol=dict(vol),
                           top={x["price"] for x in w.get("top8") or [] if x.get("price") is not None}))
    if not any(p["vol"] for p in panels):
        raise SystemExit("no darkpool_levels per-day tables in the brief")
    price = b.get("price") or {}
    bars = price.get("last_22_bars") or []
    close = (price.get("derived") or {}).get("close") or (bars[-1][4] if bars else None)
    return b.get("ticker") or "?", b.get("target_date") or "?", panels, bars, close


def draw(path, out, asof=None, zones=None):
    """asof = "HH:MM" for an intraday chart: labels say 盘中 / 现价 instead of 收盘.
    zones = [(lo, hi, text)]: a watch zone shaded on every card, its text written on the 当天新增 card."""
    T, D, panels, bars, close = load(path)

    # one price axis for all cards: the 1M regular-session range, widened to hold each window's volume bar the tails
    w1m = panels[0]["w"]
    rth = [x for x in bars if w1m.get("from") and w1m["from"] <= x[0] <= w1m["to"]]
    lo = min([x[3] for x in rth] + [wquantile(sorted(p["vol"].items()), TAIL) for p in panels if p["vol"]])
    hi = max([x[2] for x in rth] + [wquantile(sorted(p["vol"].items()), 1 - TAIL) for p in panels if p["vol"]])
    step = nice(hi - lo, MAX_BINS, BIN_STEPS)
    k_lo, k_hi = math.floor(lo / step + 1e-9), math.floor(hi / step + 1e-9)   # bin k = [k*step, (k+1)*step)
    y0, y1 = k_lo * step, (k_hi + 1) * step

    outside = 0.0
    for p in panels:
        bins, cut = defaultdict(float), 0.0
        for price, dark in p["vol"].items():
            k = math.floor(price / step + 1e-9)
            if k_lo <= k <= k_hi:
                bins[k] += dark
            else:
                cut += dark
        tot = sum(p["vol"].values())
        outside = max(outside, cut / tot if tot else 0.0)
        p["bins"] = bins
        p["top_bins"] = {math.floor(x / step + 1e-9) for x in p["top"]}

    LM, CW, GAP = 0.6, 3.0, 0.9
    FW, FH = 2 * LM + len(panels) * CW + (len(panels) - 1) * GAP, 6.9
    fig = plt.figure(figsize=(FW, FH), dpi=200, facecolor=PAGE)
    bg = fig.add_axes([0, 0, 1, 1], zorder=0)
    bg.set_xlim(0, FW)
    bg.set_ylim(0, FH)
    bg.axis("off")
    CY0, CY1 = 0.82, FH - 1.08
    AX_PAD_L, AX_PAD_R, AX_TOP, AX_BOT = 0.5, 0.18, 1.18, 0.22

    bg.text(LM, FH - 0.45, f"{T} 暗池灰色重心迁移", fontproperties=BOLD, fontsize=17, color=INK, va="center")
    head = (f"截至 {D} {asof} ET（盘中）" + (f" · 现价 {close:.2f}" if close else "") if asof else
            f"截至 {D} 收盘" + (f" · 收 {close:.2f}" if close else ""))
    bg.text(FW - LM, FH - 0.45, head, fontproperties=REG,
            fontsize=10.5, color=MUTED, va="center", ha="right")

    ly, lx = FH - 0.85, LM
    items = [("bar", BAR_TOP, "前 8 档（重心按这 8 档加权）"), ("bar", BAR_REST, "其余价位"), ("line", CENTROID, "重心")]
    if close:
        items.append(("line", CLOSE, f"{md(D)} {asof} 现价 {close:.2f}" if asof else f"{md(D)} 收盘 {close:.2f}"))
    fig.canvas.draw()
    for kind, col, label in items:
        if kind == "bar":
            bg.add_patch(Rectangle((lx, ly - 0.045), 0.32, 0.09, color=col, lw=0))
        else:
            bg.add_line(Line2D([lx, lx + 0.32], [ly, ly], color=col, lw=2.0 if col == CENTROID else 1.2))
        t = bg.text(lx + 0.42, ly, label, fontproperties=REG, fontsize=9.5, color=INK2, va="center")
        lx = t.get_window_extent(renderer=fig.canvas.get_renderer()).transformed(bg.transData.inverted()).x1 + 0.38

    tstep = nice(y1 - y0, MAX_TICKS, TICK_STEPS)
    ticks = [t * tstep for t in range(math.ceil(y0 / tstep - 1e-9), math.floor(y1 / tstep + 1e-9) + 1)]
    dec = next(d for d in range(3) if abs(tstep * 10 ** d - round(tstep * 10 ** d)) < 1e-9)   # 2.5 -> "32.5", not "32"
    tick_fmt = f"{{:.{dec}f}}"
    axes_mid = None
    for i, p in enumerate(panels):
        x0, w = LM + i * (CW + GAP), p["w"]
        bg.add_patch(FancyBboxPatch((x0, CY0), CW, CY1 - CY0, boxstyle="round,pad=0,rounding_size=0.1",
                                    fc=PAGE, ec=CARD_EDGE, lw=1.6))
        bg.text(x0 + 0.2, CY1 - 0.3, p["title"], fontproperties=BOLD, fontsize=13.5, color=INK, va="center")
        days = w.get("days_present")
        sub = f"{p['key']} · {md(w['from'])}–{md(w['to'])} · {days} 个交易日" if w.get("from") else f"{p['key']} · 无数据"
        if days is not None and days < p["sessions"]:
            sub += f"（应有 {p['sessions']}）"
        m = panels[0]["w"]   # the 1D card: the day's dark volume against the 1M daily average
        if p["key"] == "1D" and w.get("from") and w.get("dark_total") and m.get("dark_total") and m.get("days_present"):
            sub = (f"1D · {md(w['from'])} · {w['dark_total'] / 1e4:,.0f} 万股 · "
                   f"1M 日均的 {w['dark_total'] / (m['dark_total'] / m['days_present']):.2f} 倍")
        st_ = bg.text(x0 + 0.2, CY1 - 0.6, sub, fontproperties=REG, fontsize=8.8, color=MUTED, va="center")
        fs = 8.8   # shrink a subtitle that would run past the card edge
        while fs > 6.4 and st_.get_window_extent(renderer=fig.canvas.get_renderer()).transformed(
                bg.transData.inverted()).x1 > x0 + CW - 0.12:
            fs -= 0.3
            st_.set_fontsize(fs)
        c, poc = w.get("centroid_top8"), w.get("poc")
        bg.text(x0 + 0.2, CY1 - 0.88, f"重心 {c:.2f}" if c is not None else "重心 –", fontproperties=REG,
                fontsize=10, color=INK2, va="center")
        bg.text(x0 + 1.55, CY1 - 0.88, f"POC {poc:g}" if poc is not None else "POC –", fontproperties=REG,
                fontsize=10, color=INK2, va="center")

        ax_x0, ax_y0 = x0 + AX_PAD_L, CY0 + AX_BOT
        pad_r = 0.62 if p["key"] == "1D" else AX_PAD_R   # the 1D card keeps a column right of the bars for labels
        ax_w, ax_h = CW - AX_PAD_L - pad_r, (CY1 - AX_TOP) - ax_y0
        ax = fig.add_axes([ax_x0 / FW, ax_y0 / FH, ax_w / FW, ax_h / FH], zorder=2)
        ax.patch.set_alpha(0)
        axes_mid = ax_y0 + ax_h / 2
        vmax = max(p["bins"].values(), default=0.0) or 1.0
        ax.set_xlim(vmax * 1.34, 0)   # bars grow leftward from the right edge, like the rulebook figure
        ax.set_ylim(y0, y1)
        for s in ax.spines.values():
            s.set_visible(False)
        ax.set_xticks([])
        ax.set_yticks(ticks)
        ax.set_yticklabels([tick_fmt.format(t) for t in ticks], fontproperties=REG, fontsize=8.2, color=MUTED)
        ax.tick_params(axis="y", length=0, pad=4)
        for t in ticks:
            ax.axhline(t, color=GRID, lw=0.8, zorder=0)
        bar_h = min(0.62 * step, BAR_MAX_IN / ax_h * (y1 - y0))
        for k, v in sorted(p["bins"].items()):
            ax.barh((k + 0.5) * step, v, height=bar_h, color=BAR_TOP if k in p["top_bins"] else BAR_REST,
                    lw=0, zorder=2)
        if close:
            ax.axhline(close, color=CLOSE, lw=1.0, zorder=1)   # behind the bars so it never splits one
        ct = None
        if c is not None:
            ax.axhline(c, color=CENTROID, lw=1.9, zorder=4)
            ct = ax.text(vmax * 1.34, c, f"{c:.2f}", fontproperties=REG, fontsize=9, color=INK, ha="left",
                         va="center", zorder=5, clip_on=False, bbox=dict(boxstyle="round,pad=0.16", fc="white", ec="none"))
        line_h = 0.13 / ax_h * (y1 - y0)   # one small text line, in price units
        rend, taken = fig.canvas.get_renderer(), [ct.get_window_extent(fig.canvas.get_renderer())] if ct else []
        for lo_, hi_, ztxt in zones or []:
            ax.axhspan(lo_, hi_, color=ZONE, alpha=0.16, lw=0, zorder=0)
            if p["key"] == "1D" and ztxt:   # above the band when it sits above the day's centroid, else below it
                above = c is None or (lo_ + hi_) / 2 >= c
                zt = ax.text(vmax * 1.32, hi_ + line_h * 0.15 if above else lo_ - line_h * 0.15, ztxt,
                             fontproperties=REG, fontsize=7.8, color="#9a5b00", ha="left",
                             va="bottom" if above else "top", zorder=6, clip_on=False)
                taken.append(zt.get_window_extent(rend))
        if p["key"] == "1D" and p["bins"]:   # how much the busiest bins added that day (Olivia 11-12 "新增多少可以标记出来")
            placed, top = [], max(p["bins"].values())
            for k, v in sorted(p["bins"].items(), key=lambda kv: -kv[1])[:6]:
                y = (k + 0.5) * step
                if v < 0.15 * top or any(abs(y - q) < line_h for q in placed):
                    continue
                t = ax.text(1.03, y, wan(v), transform=ax.get_yaxis_transform(), fontproperties=REG, fontsize=7.4,
                            color=INK2, ha="left", va="center", zorder=6, clip_on=False)
                if any(t.get_window_extent(rend).overlaps(b) for b in taken):
                    t.remove()
                    continue
                placed.append(y)
        if not p["bins"]:
            ax.text(0.5, 0.5, "无数据", transform=ax.transAxes, fontproperties=REG, fontsize=11, color=MUTED,
                    ha="center", va="center")

    # arrows: change of the (rounded) centroid between windows, numbers only - no up/down wording
    cs = [round(p["w"]["centroid_top8"], 2) if p["w"].get("centroid_top8") is not None else None for p in panels]
    for i in range(len(panels) - 1):
        xa = LM + (i + 1) * CW + i * GAP
        bg.add_patch(FancyArrowPatch((xa + 0.16, axes_mid), (xa + GAP - 0.16, axes_mid),
                                     arrowstyle="-|>,head_length=0.32,head_width=0.18", mutation_scale=20,
                                     color=ARROW, lw=2.2))
        c0, c1 = cs[i], cs[i + 1]
        top, bottom = (f"{c1 - c0:+.2f}", f"{100 * (c1 - c0) / c0:+.2f}%") if None not in (c0, c1) else ("–", "")
        bg.text(xa + GAP / 2, axes_mid + 0.25, top, fontproperties=REG, fontsize=10.5, color=INK2,
                ha="center", va="center")
        bg.text(xa + GAP / 2, axes_mid - 0.25, bottom, fontproperties=REG, fontsize=9.5, color=MUTED,
                ha="center", va="center")

    pct = "<0.001%" if 100 * outside < 0.0005 else f"{100 * outside:.3f}%"   # never print "0.000%" for a nonzero share
    foot = [f"数据：UW darkpool price-levels（场外成交量按价位全天汇总，含盘前盘后）。UW 每档约 $1 宽、价位标在区间下沿，"
            f"图上每 ${step:g} 合并一格；深色柱 = 含本窗口 dark 量前 8 档的价位。",
            "每个窗口的柱长按本窗口最大一格归一，窗口之间只比位置和形状。"
            + (f"价格区间外的零星成交未画（最多占窗口的 {pct}）。" if outside > 0 else "")]
    for k, s in enumerate(foot):
        bg.text(LM, 0.46 - k * 0.22, s, fontproperties=REG, fontsize=7.8, color=MUTED, va="center", parse_math=False)

    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    fig.savefig(out, dpi=200, facecolor=PAGE)
    plt.close(fig)
    return dict(ticker=T, date=D, step=step, range=[y0, y1], outside=outside)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="dp_chart.py")
    ap.add_argument("--brief", required=True, help="analysis_data/<D>/<T>.json")
    ap.add_argument("--out", required=True, help="PNG path")
    ap.add_argument("--asof", help="HH:MM ET for an intraday chart (labels 盘中 / 现价 instead of 收盘)")
    ap.add_argument("--zone", action="append", default=[], help="LO,HI,TEXT watch zone to shade (repeatable)")
    a = ap.parse_args(argv)
    zones = [(float(z.split(",", 2)[0]), float(z.split(",", 2)[1]), z.split(",", 2)[2] if z.count(",") >= 2 else "")
             for z in a.zone]
    info = draw(a.brief, a.out, a.asof, zones)
    print(f"{info['ticker']} {info['date']} bin ${info['step']:g} range {info['range'][0]:g}–{info['range'][1]:g} "
          f"outside {100 * info['outside']:.4f}% -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
