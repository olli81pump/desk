"""FOMO Solana trading fees. Gas is 0 (FOMO pays it)."""

from __future__ import annotations


def fee_usd(ticket_usd: float, ref_discount: float = 0.10) -> float:
    """Fee for one side of a trade, after the referral discount."""
    t = float(ticket_usd)
    if t < 5:
        raw = 0.0
    elif t < 47.50:
        raw = 0.02 * t
    elif t <= 190:
        raw = 0.95
    else:
        raw = 0.005 * t
    disc = min(max(float(ref_discount), 0.0), 1.0)
    return round(raw * (1.0 - disc), 6)


def round_trip_fees(ticket_usd: float, ref_discount: float = 0.10) -> float:
    return round(fee_usd(ticket_usd, ref_discount) * 2.0, 6)
