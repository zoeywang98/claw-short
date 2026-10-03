#!/usr/bin/env python3
"""Draw the SHORT_ENGINE §4.2 DP grey-centroid migration chart (1M / 1W / 2D) for one ticker from its brief.

Layout follows the rulebook figure: three cards on one shared price axis, dark-pool volume per price as grey bars
growing leftward from the right edge, an arrow between cards. Data only: bars, centroid_top8, poc, the day's
close and the centroid change between windows. The direction call stays in the analysis text.

Needs matplotlib: the system /usr/bin/python3 has it, the homebrew python3 that run.sh's PATH picks does not.

usage: dp_chart.py --brief analysis_data/<D>/<T>.json --out chart.png
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

PANELS = [("1M", "长周期", 21), ("1W", "中周期", 5), ("2D", "短周期", 2)]   # window, title, sessions
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


def font(*paths):
    for p in paths:
        if os.path.exists(p):
            return fm.FontProperties(fname=p)
    return fm.FontProperties()


REG = font("/System/Library/Fonts/Hiragino Sans GB.ttc", "/Library/Fonts/Arial Unicode.ttf")
BOLD = font("/System/Library/Fonts/STHeiti Medium.ttc", "/System/Library/Fonts/Hiragino Sans GB.ttc")


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


def draw(path, out):
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

    FW, FH = 12.0, 6.9
    fig = plt.figure(figsize=(FW, FH), dpi=200, facecolor=PAGE)
    bg = fig.add_axes([0, 0, 1, 1], zorder=0)
    bg.set_xlim(0, FW)
    bg.set_ylim(0, FH)
    bg.axis("off")
    LM, CW, GAP = 0.6, 3.0, 0.9
    CY0, CY1 = 0.82, FH - 1.08
    AX_PAD_L, AX_PAD_R, AX_TOP, AX_BOT = 0.5, 0.18, 1.18, 0.22

    bg.text(LM, FH - 0.45, f"{T} 暗池灰色重心迁移", fontproperties=BOLD, fontsize=17, color=INK, va="center")
    bg.text(FW - LM, FH - 0.45, f"截至 {D} 收盘" + (f" · 收 {close:.2f}" if close else ""), fontproperties=REG,
            fontsize=10.5, color=MUTED, va="center", ha="right")

    ly, lx = FH - 0.85, LM
    items = [("bar", BAR_TOP, "前 8 档（重心按这 8 档加权）"), ("bar", BAR_REST, "其余价位"), ("line", CENTROID, "重心")]
    if close:
        items.append(("line", CLOSE, f"{md(D)} 收盘 {close:.2f}"))
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
    tick_fmt = "{:.2f}" if tstep < 0.5 else "{:.1f}" if tstep < 1 else "{:.0f}"
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
        bg.text(x0 + 0.2, CY1 - 0.6, sub, fontproperties=REG, fontsize=8.8, color=MUTED, va="center")
        c, poc = w.get("centroid_top8"), w.get("poc")
        bg.text(x0 + 0.2, CY1 - 0.88, f"重心 {c:.2f}" if c is not None else "重心 –", fontproperties=REG,
                fontsize=10, color=INK2, va="center")
        bg.text(x0 + 1.55, CY1 - 0.88, f"POC {poc:g}" if poc is not None else "POC –", fontproperties=REG,
                fontsize=10, color=INK2, va="center")

        ax_x0, ax_y0 = x0 + AX_PAD_L, CY0 + AX_BOT
        ax_w, ax_h = CW - AX_PAD_L - AX_PAD_R, (CY1 - AX_TOP) - ax_y0
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
        if c is not None:
            ax.axhline(c, color=CENTROID, lw=1.9, zorder=4)
            ax.text(vmax * 1.34, c, f"{c:.2f}", fontproperties=REG, fontsize=9, color=INK, ha="left", va="center",
                    zorder=5, clip_on=False, bbox=dict(boxstyle="round,pad=0.16", fc="white", ec="none"))
        if not p["bins"]:
            ax.text(0.5, 0.5, "无数据", transform=ax.transAxes, fontproperties=REG, fontsize=11, color=MUTED,
                    ha="center", va="center")

    # arrows: change of the (rounded) centroid between windows, numbers only - no up/down wording
    cs = [round(p["w"]["centroid_top8"], 2) if p["w"].get("centroid_top8") is not None else None for p in panels]
    for i in range(2):
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

    foot = [f"数据：UW darkpool price-levels（场外成交量按价位全天汇总，含盘前盘后）。UW 每档约 $1 宽、价位标在区间下沿，"
            f"图上每 ${step:g} 合并一格；深色柱 = 含本窗口 dark 量前 8 档的价位。",
            "每个窗口的柱长按本窗口最大一格归一，窗口之间只比位置和形状。"
            + (f"价格区间外的零星成交未画（最多占窗口的 {100 * outside:.3f}%）。" if outside > 0 else "")]
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
    a = ap.parse_args(argv)
    info = draw(a.brief, a.out)
    print(f"{info['ticker']} {info['date']} bin ${info['step']:g} range {info['range'][0]:g}–{info['range'][1]:g} "
          f"outside {100 * info['outside']:.4f}% -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
