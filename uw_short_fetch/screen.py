#!/usr/bin/env python3
"""Apply SHORT_ENGINE.md gates to a fetched run: python3 screen.py [data/<run>]  (default: newest run)."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from uwsf.screen import screen  # noqa: E402

if __name__ == "__main__":
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    run = sys.argv[1] if len(sys.argv) > 1 else max((os.path.join(base, d) for d in os.listdir(base)
                                                     if os.path.isdir(os.path.join(base, d))), key=os.path.getmtime)
    out = screen(run)
    path = os.path.join(run, "screen.json")
    with open(path, "w") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1, default=str)
    for r in out["results"]:
        print(f"{r['ticker']:5s} {r['group'] or '':10s} {r['verdict']:14s} {r['why']}")
    print(f"\nfull detail: {path}")
