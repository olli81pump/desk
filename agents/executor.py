"""Executor: arithmetic and one Buy button. Never places an order."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def size_position(stack: float, liq: float | None, s: dict, free: float | None = None) -> dict[str, Any]:
    """Compute ticket size. Does not place an order."""
    raw = float(stack) * float(s["stack_pct"]) / 100.0
    caps = ["stack_pct"]
    size = raw
    if liq is not None:
        pool_cap = float(liq) * float(s["max_pool_pct"]) / 100.0
        if size > pool_cap:
            size = pool_cap
            caps.append("max_pool_pct")
    min_t = float(s["min_ticket_usd"])
    below = s.get("below_min", "bump")
    skipped = False
    bumped = False
    reason = None
    if size + 1e-9 < min_t:
        if below == "bump":
            size = min_t
            bumped = True
            caps.append("below_min_bump")
        else:
            skipped = True
            reason = f"size ${size:.2f} under min ticket ${min_t:.2f}"
            caps.append("below_min_skip")
    if free is not None and not skipped and size > free + 1e-9:
        skipped = True
        reason = "not enough free stack"
    return {
        "raw": raw,
        "size": 0.0 if skipped else size,
        "caps": caps,
        "skipped": skipped,
        "bumped": bumped,
        "reason": reason,
        "stack_pct_effective": (size / stack * 100.0) if stack and not skipped else 0.0,
    }


def recheck(signal_price: float, signal_liq: float | None, fresh: dict, s: dict) -> str | None:
    """Return a skip reason or None if the push may go out."""
    price = fresh.get("priceUsd")
    try:
        price_f = float(price)
    except (TypeError, ValueError):
        return "no price"
    if signal_price and price_f > signal_price * (1.0 + float(s["recheck_price_up_pct"]) / 100.0):
        return "price ran"
    liq = fresh.get("liquidity_usd")
    if signal_liq and liq is not None:
        try:
            liq_f = float(liq)
        except (TypeError, ValueError):
            liq_f = None
        if liq_f is not None and liq_f < signal_liq * (1.0 - float(s["recheck_liq_drop_pct"]) / 100.0):
            return "liquidity dropped"
    return None


def execution_payload(mint: str, signal_price: float, size: float, stack: float, link: str, mode: str,
                      status: str, reason: str | None = None) -> dict:
    return {
        "agent": "executor",
        "mint": mint,
        "signalPrice": signal_price,
        "sizeUsd": size,
        "stackPct": (size / stack * 100.0) if stack else 0.0,
        "link": link,
        "mode": mode,
        "status": status,
        "reason": reason,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
