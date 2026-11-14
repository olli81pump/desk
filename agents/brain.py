"""Brain: sizes every buy from the analyst score. Never places an order."""

from __future__ import annotations

from typing import Any


def size_buy(
    score: float,
    liq: float | None,
    stack: float,
    free: float | None,
    s: dict,
    mint: str = "",
) -> dict[str, Any]:
    """Linear size from analyst score, then pool and free-stack caps.

    Score 70 -> min_size_usd ($5), score 100 -> max_size_usd ($10).
    After caps, a ticket under min_size_usd is skipped.
    """
    lo = float(s.get("min_size_usd") if s.get("min_size_usd") is not None else 5)
    hi = float(s.get("max_size_usd") if s.get("max_size_usd") is not None else 10)
    if hi < lo:
        hi = lo
    max_pool = float(s.get("max_pool_pct") if s.get("max_pool_pct") is not None else 2)
    try:
        score_f = float(score)
    except (TypeError, ValueError):
        score_f = 0.0
    t = (score_f - 70.0) / 30.0
    t = max(0.0, min(1.0, t))
    raw = lo + t * (hi - lo)
    size = raw
    cap_hit = None
    if liq is not None:
        try:
            pool_cap = float(liq) * max_pool / 100.0
        except (TypeError, ValueError):
            pool_cap = None
        if pool_cap is not None and size > pool_cap + 1e-12:
            size = pool_cap
            cap_hit = "max_pool_pct"
    if free is not None:
        try:
            free_f = float(free)
        except (TypeError, ValueError):
            free_f = None
        if free_f is not None and size > free_f + 1e-12:
            size = max(0.0, free_f)
            cap_hit = "free_stack"
    skipped = size + 1e-9 < lo
    reason = None
    if skipped:
        if cap_hit == "max_pool_pct":
            reason = f"size ${size:.2f} under ${lo:.2f} after pool cap"
        elif cap_hit == "free_stack":
            reason = f"size ${size:.2f} under ${lo:.2f} after free stack cap"
        else:
            reason = f"size ${size:.2f} under ${lo:.2f}"
        sized = 0.0
    else:
        sized = size
    stack_pct = (sized / float(stack) * 100.0) if stack and not skipped else 0.0
    return {
        "agent": "brain",
        "mint": mint,
        "score": score_f,
        "sizeUsd": sized,
        "stackPct": stack_pct,
        "capHit": cap_hit,
        "reason": reason,
        "skipped": skipped,
        "raw": raw,
    }
