"""Default candidate watchlist, grouped by theme. Used when --tickers / --tickers-file are not given."""
from __future__ import annotations

from typing import Dict, List

# slug -> (label, tickers)
WATCHLIST: Dict[str, Dict[str, object]] = {
    "optics": {"label": "光模块/光学", "tickers": ["LITE", "COHR", "AAOI", "GLW", "AEHR"]},
    "ai_infra": {"label": "AI基建/电力", "tickers": ["VRT", "NVT", "NBIS", "DELL", "FLEX"]},
    "software": {"label": "软件/企服", "tickers": ["MSFT", "META", "IBM", "NOW", "DDOG", "MDB"]},
    "pharma": {"label": "医药", "tickers": ["MRK", "RVMD", "CRVS", "VKTX", "TEVA", "VTRS"]},
    "commodity_etf": {"label": "商品ETF", "tickers": ["SLV"]},
}


def resolve_groups(spec: str = "") -> Dict[str, Dict[str, object]]:
    """Pick groups by comma-separated slug or label; empty spec means all groups."""
    if not spec.strip():
        return dict(WATCHLIST)
    out: Dict[str, Dict[str, object]] = {}
    for part in (p.strip() for p in spec.split(",") if p.strip()):
        hit = [k for k, v in WATCHLIST.items() if part.lower() == k or part == v["label"]]
        if not hit:
            raise SystemExit(f"unknown group {part!r}; choose from: " +
                             ", ".join(f"{k} ({v['label']})" for k, v in WATCHLIST.items()))
        out[hit[0]] = WATCHLIST[hit[0]]
    return out


def tickers_of(groups: Dict[str, Dict[str, object]]) -> List[str]:
    out: List[str] = []
    for g in groups.values():
        for t in g["tickers"]:  # type: ignore[union-attr]
            if t not in out:
                out.append(t)
    return out


def group_of(ticker: str) -> str:
    for g in WATCHLIST.values():
        if ticker in g["tickers"]:  # type: ignore[operator]
            return str(g["label"])
    return ""
