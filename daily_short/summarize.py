#!/usr/bin/env python3
"""After the per-ticker posts: one summary post for the whole scan.

A bare `claude -p` call condenses the day's replies (logs/<D>/<T>.reply.json) into the channel's tiered format;
the run-stats line under it (done / failed, UW requests, elapsed) is computed here, not by the model.

usage: summarize.py --date D --tickers T1,T2,... [--failed T3,...] [--elapsed SECONDS] [--dry-run]
"""
import argparse
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze import HERE, MODEL, send_text  # noqa: E402

RUNS = "/Users/yuwang/.openclaw/workspace-claw-short/uw_short_fetch/runs"
SYSTEM = """你把当天做空扫描里每只票的分析结论汇总成一条 Discord 帖子。

格式（严格遵守，总长 ≤1600 字符）：
**做空扫描汇总 · <日期>**
✅ 做空候选：每只一行 `TICKER 置信度 · 一句依据 · 失效位 · 财报日`；没有就写"✅ 无"
👀 观察：有才写，一行列完票名，括号里给降级原因（如 caveat / THIN / 财报 7 天内 / 挤压反噬）
⚪ 不构成 setup：一行列完票名，括号里给最主要的原因（如 量薄 / 吸筹 / 指纹不符）
🧨 禁止做空（squeeze-watch）：有才写，一行列完票名，括号里给 flip 收复位
⛔ 熔断：有才写，写名单负 gamma X/23
末尾用一句话总结全场（熔断与否、共同特征），不要写"最后一行"几个字

纪律：只用下面各票分析里出现的结论和数字，不新增判断，不改动任何票的结论档位；不要前言和客套。"""


def uw_requests(date, tickers):
    total = 0
    for path in [f"{RUNS}/market/{date}/run_log.txt"] + [f"{RUNS}/tickers/{t}/{date}/run_log.txt" for t in tickers]:
        try:
            m = re.search(r"this run: (\d+) requests", open(path).read())
            total += int(m.group(1)) if m else 0
        except OSError:
            pass
    return total


def main(argv=None):
    ap = argparse.ArgumentParser(prog="summarize.py")
    ap.add_argument("--date", required=True)
    ap.add_argument("--tickers", required=True)
    ap.add_argument("--failed", default="")
    ap.add_argument("--elapsed", type=int, default=0)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    tickers = [t for t in a.tickers.split(",") if t]
    failed = [t for t in a.failed.split(",") if t]
    log = os.path.join(HERE, "logs", a.date)

    parts = []
    for t in tickers:
        if t in failed:
            continue
        try:
            parts.append(json.load(open(os.path.join(log, f"{t}.reply.json")))["result"])
        except (OSError, KeyError, ValueError):
            failed.append(t)
    stats = (f"完成 {len(tickers) - len(failed)}/{len(tickers)}"
             + (f" · 失败 {', '.join(failed)}" if failed else "")
             + f" · UW 调用 {uw_requests(a.date, tickers)} 次 · 用时 {a.elapsed // 60} 分钟")

    body = ""
    if parts:
        cmd = ["claude", "-p", "--model", MODEL, "--effort", "medium", "--system-prompt", SYSTEM,
               "--tools", "", "--strict-mcp-config", "--setting-sources", "",
               "--no-session-persistence", "--output-format", "json"]
        user = f"日期 {a.date}\n\n" + "\n\n---\n\n".join(parts)
        p = subprocess.run(cmd, input=user, capture_output=True, text=True,
                           cwd=os.path.join(HERE, "sandbox"), timeout=600)
        try:
            r = json.loads(p.stdout)
            body = "" if r.get("is_error") else (r.get("result") or "")
        except json.JSONDecodeError:
            body = ""
        with open(os.path.join(log, "_summary.reply.json"), "w") as f:
            f.write(p.stdout or p.stderr)
    text = (body.strip() or f"**做空扫描汇总 · {a.date}**\n（汇总生成失败，各票结论见上方帖子）") + f"\n\n{stats}"
    print(text)
    if not a.dry_run:
        send_text(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
