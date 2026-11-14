"""Analyst: rules-mode gate. Jev is not used (analyst_mode=rules)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def rules_answers(dex: dict, bundled: int | None, s: dict) -> dict[str, float]:
    vol_h1 = float(dex.get("volume_h1") or 0)
    buys_h1 = float(dex.get("txns_h1_buys") or 0)
    buys_m5 = float(dex.get("txns_m5_buys") or 0)
    sells_m5 = float(dex.get("txns_m5_sells") or 0)
    ch_m5 = float(dex.get("priceChange_m5") or 0)
    ch_h1 = float(dex.get("priceChange_h1") or 0)

    alive = clamp(vol_h1 / float(s["alive_volume_h1"]))
    organic = clamp(buys_h1 / float(s["organic_buys_h1"]))
    if bundled is not None and bundled >= int(s.get("bundled_penalty_at", 3)):
        organic = clamp(organic * float(s["bundled_penalty"]))
    drop = float(s["flush_drop_m5_pct"])
    if ch_m5 <= -drop and buys_m5 >= sells_m5:
        flush = 1.0
    elif ch_m5 < 0:
        flush = 0.5
    else:
        flush = 0.0
    chase = clamp(ch_h1 / float(s["chase_h1_pct"]))
    return {"alive_6h": alive, "organic": organic, "flush": flush, "chase": chase}


def score_of(a: dict[str, float]) -> int:
    return int(round(100 * (a["alive_6h"] + a["organic"] + a["flush"] + (1.0 - a["chase"])) / 4.0))


def gate(answers: dict[str, float], s: dict) -> tuple[bool, int, list[str]]:
    failed: list[str] = []
    if answers["alive_6h"] < float(s["min_alive_6h"]):
        failed.append(f"alive_6h {answers['alive_6h']:.2f}")
    if answers["organic"] < float(s["min_organic"]):
        failed.append(f"organic {answers['organic']:.2f}")
    if answers["chase"] > float(s["max_chase"]):
        failed.append(f"chase {answers['chase']:.2f}")
    sc = score_of(answers)
    if sc < int(s["min_score"]):
        failed.append(f"score {sc}")
    return (len(failed) == 0, sc, failed)


def build_state_text(name: str, age_min: int, dex: dict, audit: dict) -> str:
    """Numbers only, no opinions, no thresholds, no 'buy', no balance."""
    dev = audit.get("dev") or "n/a"
    lp = audit.get("lp") or "n/a"
    bund = audit.get("bundled")
    bund_s = "None" if not bund else str(bund)
    delg = audit.get("delegations") or "None"
    text = (
        f"Coin {name} on Solana, graduated {age_min} min ago. "
        f"Liquidity ${dex.get('liquidity_usd')}. Market cap ${dex.get('marketCap')}. "
        f"Last 5 min: {dex.get('txns_m5_buys')} buys, {dex.get('txns_m5_sells')} sells, "
        f"volume ${dex.get('volume_m5')}, price {dex.get('priceChange_m5')}%. "
        f"Last 1h: {dex.get('txns_h1_buys')} buys, {dex.get('txns_h1_sells')} sells, "
        f"volume ${dex.get('volume_h1')}, price {dex.get('priceChange_h1')}%. "
        f"Top 10 hold {audit.get('top10')}%. Dev holds {dev}, sold 0. "
        f"LP {lp}. Bundled {bund_s}. Delegations {delg}."
    )
    return text[:3000]


def analyse(dex: dict, audit: dict, s: dict, mint: str, name: str = "") -> dict:
    bundled = audit.get("bundled_n")
    answers = rules_answers(dex, bundled, s)
    passed, sc, failed = gate(answers, s)
    return {
        "agent": "analyst",
        "mint": mint,
        "answers": answers,
        "score": sc,
        "passed": passed,
        "failed": failed,
        "model": "rules",
        "inputTokens": 0,
        "ts": datetime.now(timezone.utc).isoformat(),
        "name": name,
    }
