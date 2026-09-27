#!/usr/bin/env python3
"""Entry point: python3 fetch.py --tickers NBIS,AXTI [--date YYYY-MM-DD] ..."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from uwsf.pipeline import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
