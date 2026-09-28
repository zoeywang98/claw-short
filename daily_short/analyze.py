#!/usr/bin/env python3
"""Analyse one ticker's brief with a bare `claude -p` call, then post the reply to Discord as claw-short.

Calls Claude Code directly instead of `openclaw agent`, whose CLI backend runs the full Claude Code harness
(default system prompt, built-in tools, user plugins/MCP). Here the model sees only INSTRUCTIONS.md + SHORT_ENGINE.md + market brief (system prompt, identical for every
ticker of the day so it caches) and the ticker brief (stdin).

usage: analyze.py --date D --ticker T [--brief PATH] [--market-brief PATH] [--dry-run]
       (paths default to uw_short_fetch/data/<D>/...)
"""
import argparse
import json
import os
import subprocess
import sys
import time

WS = "/Users/yuwang/.openclaw/workspace-claw-short"
HERE = os.path.join(WS, "daily_short")
DATA = os.path.join(WS, "uw_short_fetch", "data")
MODEL = "claude-opus-5-5[1m]"
EFFORT = "high"
TIMEOUT_S = 1200
CHANNEL = "channel:1553568018200657973"
ACCOUNT = "default"   # openclaw Discord account id bound to the claw-short agent (there is no "claw-short" account)
DISCORD_CHUNK = 1900


def system_prompt(market_brief):
    parts = [open(os.path.join(HERE, "INSTRUCTIONS.md")).read(),
             "## SHORT_ENGINE.md\n\n" + open(os.path.join(WS, "SHORT_ENGINE.md")).read(),
             "## 当日市场数据（market_brief）\n\n" + open(market_brief).read()]
    return "\n\n".join(parts)


def chunks(text, limit=DISCORD_CHUNK):
    """Split on line boundaries so each Discord message stays under the 2000-char cap."""
    out, cur = [], ""
    for line in text.splitlines(keepends=True):
        while len(line) > limit:
            if cur:
                out.append(cur)
                cur = ""
            out.append(line[:limit])
            line = line[limit:]
        if len(cur) + len(line) > limit:
            out.append(cur)
            cur = ""
        cur += line
    if cur.strip():
        out.append(cur)
    return out


def send_text(text):
    post(text)


def post(text):
    for part in chunks(text):
        subprocess.run(["openclaw", "message", "send", "--channel", "discord", "--account", ACCOUNT,
                        "--target", CHANNEL, "--message", part], check=True,
                       stdout=subprocess.DEVNULL, timeout=120)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="analyze.py")
    ap.add_argument("--date", required=True)
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--brief", help="default: data/<D>/<T>/brief.json")
    ap.add_argument("--market-brief", help="default: data/<D>/market_brief.json")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    a.brief = a.brief or os.path.join(DATA, a.date, a.ticker, "brief.json")
    a.market_brief = a.market_brief or os.path.join(DATA, a.date, "market_brief.json")

    log = os.path.join(HERE, "logs", a.date)
    os.makedirs(log, exist_ok=True)
    brief = open(a.brief).read()
    user = f"## 本票数据（{a.ticker} brief）\n\n{brief}"
    sandbox = os.path.join(HERE, "sandbox")   # empty cwd: no project CLAUDE.md / memory gets picked up
    os.makedirs(sandbox, exist_ok=True)
    cmd = ["claude", "-p", "--model", MODEL, "--effort", EFFORT,
           "--system-prompt", system_prompt(a.market_brief),
           "--tools", "", "--strict-mcp-config", "--setting-sources", "",
           "--no-session-persistence", "--output-format", "json"]
    t0 = time.time()
    p = subprocess.run(cmd, input=user, capture_output=True, text=True, cwd=sandbox, timeout=TIMEOUT_S)
    elapsed = round(time.time() - t0)
    try:
        r = json.loads(p.stdout)
    except json.JSONDecodeError:
        r = {"is_error": True, "result": (p.stdout or p.stderr)[-2000:]}
    with open(os.path.join(log, f"{a.ticker}.reply.json"), "w") as f:
        json.dump(r, f, ensure_ascii=False, indent=1)
    u = r.get("usage") or {}
    print(f"{a.ticker} {elapsed}s in={u.get('input_tokens', 0) + u.get('cache_creation_input_tokens', 0) + u.get('cache_read_input_tokens', 0)}"
          f" (cache_read={u.get('cache_read_input_tokens', 0)}) out={u.get('output_tokens', 0)}")
    if p.returncode != 0 or r.get("is_error") or not r.get("result"):
        print(f"❌ {a.ticker}: {str(r.get('result'))[:500]}", file=sys.stderr)
        return 1
    if not a.dry_run:
        post(r["result"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
