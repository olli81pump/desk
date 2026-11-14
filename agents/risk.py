"""Risk: exit rules. Never places an order. Stops never move down."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any


def tighter_stop(old_pct: float, new_pct: float) -> float:
    """A new stop applies to open positions only if it is tighter (smaller %).

    Loosening (e.g. 6 -> 8) would move the stop *price* down and is refused.
    Tightening (e.g. 6 -> 4) moves the stop price up and is applied.
    """
    return min(float(old_pct), float(new_pct))


def evaluate(pos: dict, price: float, now: datetime | None, s: dict | None = None) -> dict:
    """Apply peak / stop / trail / timeout in that order. pos is not mutated until applied."""
    now = now or datetime.now(timezone.utc)
    entry = float(pos["entry_price"])
    peak = max(float(pos.get("peak_price") or entry), float(price))
    stop_pct = float(pos["stop_pct"])
    trail_start = float(pos.get("trail_start_pct") or (s or {}).get("trail_start_pct") or 20)
    trail_pct = float(pos.get("trail_pct") or (s or {}).get("trail_pct") or 12)
    timeout_h = float(pos.get("timeout_h") or (s or {}).get("timeout_h") or 3)
    timeout_min_gain = float(pos.get("timeout_min_gain_pct") or (s or {}).get("timeout_min_gain_pct") or 5)
    trail_active = bool(pos.get("trail_active"))
    opened = pos.get("opened_at")
    if isinstance(opened, str):
        opened_dt = datetime.fromisoformat(opened.replace("Z", "+00:00"))
    else:
        opened_dt = opened

    reason = None
    # stop
    if price <= entry * (1.0 - stop_pct / 100.0):
        reason = "stop"
    # trail on
    if price >= entry * (1.0 + trail_start / 100.0):
        trail_active = True
    # trail
    if reason is None and trail_active and price <= peak * (1.0 - trail_pct / 100.0):
        reason = "trail"
    # timeout: open >= timeout_h and price < entry * (1 + min_gain)
    if reason is None and opened_dt is not None:
        if now - opened_dt >= timedelta(hours=timeout_h) and price < entry * (1.0 + timeout_min_gain / 100.0):
            reason = "timeout"

    return {
        "peak": peak,
        "trail_active": trail_active,
        "reason": reason,
        "exit_price": price if reason else None,
        "stop_line": entry * (1.0 - stop_pct / 100.0),
        "trail_line": peak * (1.0 - trail_pct / 100.0) if trail_active else None,
    }


def pnl(entry: float, exit_price: float, size: float, fees: float) -> tuple[float, float]:
    if not entry:
        return 0.0, 0.0
    gross = size * ((exit_price / entry) - 1.0)
    net = gross - fees
    pct = (exit_price / entry - 1.0) * 100.0
    return net, pct
