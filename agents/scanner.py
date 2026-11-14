"""Scanner helpers: kill order, copycat, waiting room rules."""

from __future__ import annotations

import re
import unicodedata
from typing import Any


def normalize_name(s: str | None) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower()
    s = re.sub(r"[\s\d]+", "", s, flags=re.UNICODE)
    s = re.sub(r"[^\w]+", "", s, flags=re.UNICODE)
    # leftover emoji / symbols already stripped by the last sub for most cases
    return s


def is_copycat(name: str | None, symbol: str | None, runners: list[dict]) -> str | None:
    """Exact match or one name inside the other, after normalize, vs today's runners."""
    cands = [normalize_name(name), normalize_name(symbol)]
    cands = [c for c in cands if c]
    for r in runners:
        refs = [normalize_name(r.get("name")), normalize_name(r.get("symbol"))]
        refs = [x for x in refs if x]
        for a in cands:
            for b in refs:
                if a == b or (len(a) >= 3 and len(b) >= 3 and (a in b or b in a)):
                    return f"copycat of {r.get('symbol') or r.get('name') or r.get('mint')}"
    return None


def format_liq(usd: float | None) -> str:
    if usd is None:
        return "?"
    if usd >= 1000:
        return f"${usd/1000:.1f}K"
    return f"${usd:.0f}"


def scanner_kill(dex: dict, top10: float | None, age_min: float, s: dict, runners: list[dict]) -> str | None:
    """First hit wins, in this order: liq, top10, h1, copycat. Age is a pass condition, not a kill."""
    liq = dex.get("liquidity_usd")
    try:
        liq_f = float(liq) if liq is not None else None
    except (TypeError, ValueError):
        liq_f = None
    if liq_f is None:
        return None  # DexScreener doesn't know it yet — wait, don't kill
    if liq_f < float(s["min_liquidity_usd"]):
        return f"liq {format_liq(liq_f)}"
    if top10 is not None and top10 > float(s["max_top10_pct"]):
        return f"top 10 hold {top10:.0f}%"
    h1 = dex.get("priceChange_h1")
    try:
        h1_f = float(h1) if h1 is not None else None
    except (TypeError, ValueError):
        h1_f = None
    if h1_f is not None and h1_f > float(s["max_h1_change_pct"]):
        return f"+{h1_f:.0f}% in 1h"
    hit = is_copycat(dex.get("name"), dex.get("symbol"), runners)
    if hit:
        return hit
    return None


def scanner_pass(dex: dict, top10: float | None, age_min: float, s: dict, runners: list[dict]) -> tuple[str, str | None]:
    """Return (verdict, reason). pass only when age ok and no kill and DexScreener known."""
    if not dex or dex.get("priceUsd") is None or dex.get("liquidity_usd") is None:
        return "wait", None
    reason = scanner_kill(dex, top10, age_min, s, runners)
    if reason:
        return "kill", reason
    if age_min < int(s["min_pool_age_min"]):
        return "wait", None
    return "pass", None
