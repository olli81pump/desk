"""Desk settings: defaults, aliases, ranges, ticket check."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

DEFAULTS: dict[str, Any] = {
    # scanner
    "min_liquidity_usd": 40_000.0,
    "max_top10_pct": 25.0,
    "max_h1_change_pct": 80.0,
    "scanner_poll_s": 60,
    "min_pool_age_min": 10,
    "max_wait_min": 60,
    "runner_h24_pct": 300.0,
    # auditor
    "auditor_enabled": True,
    "max_dev_pct": 5.0,
    "auditor_max_top10_pct": 25.0,
    "min_lp_locked_pct": 99.0,
    "auditor_min_pool_age_min": 10,
    "max_bundled": 5,
    "max_delegated_accounts": 10,
    "auditor_retries": 3,
    # analyst
    "analyst_mode": "rules",
    "min_alive_6h": 0.70,
    "min_organic": 0.65,
    "max_chase": 0.30,
    "min_score": 70,
    "analyst_timeout_s": 10,
    "alive_volume_h1": 25_000.0,
    "organic_buys_h1": 150.0,
    "bundled_penalty": 0.5,
    "bundled_penalty_at": 3,
    "flush_drop_m5_pct": 5.0,
    "chase_h1_pct": 80.0,
    # executor
    "stack_pct": 8.0,
    "max_pool_pct": 2.0,
    "min_ticket_usd": 47.50,
    "below_min": "bump",
    "recheck_liq_drop_pct": 20.0,
    "recheck_price_up_pct": 15.0,
    "executor_confirm_window_min": 5,
    # risk
    "risk_poll_s": 15,
    "stop_pct": 6.0,
    "trail_start_pct": 20.0,
    "trail_pct": 12.0,
    "timeout_h": 3.0,
    "timeout_min_gain_pct": 5.0,
    "risk_confirm_window_min": 2,
    # desk
    "mode": "PAPER",
    "paper_start_stack": 200.0,
    "live_stack": None,
    "paper_balance": 200.0,
    "report_time": "08:00",
    "notifier": "telegram",
    "rpc_url": "https://api.mainnet-beta.solana.com",
    "push_rejects": False,
    "fees_ref_discount": 0.10,
    "fomo_handle": "olli81",
}

RANGES: dict[str, tuple[float | int | None, float | int | None]] = {
    "min_liquidity_usd": (1_000, 10_000_000),
    "max_top10_pct": (1, 100),
    "max_h1_change_pct": (1, 10_000),
    "scanner_poll_s": (5, 3_600),
    "min_pool_age_min": (0, 1_440),
    "max_wait_min": (1, 1_440),
    "runner_h24_pct": (50, 20_000),
    "max_dev_pct": (0, 100),
    "auditor_max_top10_pct": (1, 100),
    "min_lp_locked_pct": (0, 100),
    "auditor_min_pool_age_min": (0, 1_440),
    "max_bundled": (1, 1_000),
    "max_delegated_accounts": (1, 1_000),
    "auditor_retries": (1, 10),
    "min_alive_6h": (0, 1),
    "min_organic": (0, 1),
    "max_chase": (0, 1),
    "min_score": (0, 100),
    "analyst_timeout_s": (2, 60),
    "alive_volume_h1": (1, 10_000_000),
    "organic_buys_h1": (1, 100_000),
    "bundled_penalty": (0, 1),
    "bundled_penalty_at": (1, 100),
    "flush_drop_m5_pct": (0, 100),
    "chase_h1_pct": (1, 10_000),
    "stack_pct": (0.1, 100),
    "max_pool_pct": (0.1, 100),
    "min_ticket_usd": (5, 10_000),
    "recheck_liq_drop_pct": (0, 100),
    "recheck_price_up_pct": (0, 1_000),
    "executor_confirm_window_min": (1, 120),
    "risk_poll_s": (5, 600),
    "stop_pct": (0.1, 90),
    "trail_start_pct": (0.1, 1_000),
    "trail_pct": (0.1, 90),
    "timeout_h": (0.1, 72),
    "timeout_min_gain_pct": (0, 1_000),
    "risk_confirm_window_min": (1, 60),
    "paper_start_stack": (10, 1_000_000),
    "live_stack": (10, 10_000_000),
    "fees_ref_discount": (0, 0.5),
}

CHOICES: dict[str, tuple[str, ...]] = {
    "below_min": ("bump", "skip"),
    "analyst_mode": ("rules", "jev"),
    "mode": ("PAPER", "LIVE"),
    "notifier": ("telegram",),
}

# User-facing aliases -> setting key
ALIASES: dict[str, str] = {
    "stop": "stop_pct",
    "stop_pct": "stop_pct",
    "stop pct": "stop_pct",
    "trail": "trail_pct",
    "trail_pct": "trail_pct",
    "trail start": "trail_start_pct",
    "trail_start": "trail_start_pct",
    "timeout": "timeout_h",
    "timeout_h": "timeout_h",
    "stack_pct": "stack_pct",
    "stack %": "stack_pct",
    "min ticket": "min_ticket_usd",
    "min_ticket": "min_ticket_usd",
    "min_ticket_usd": "min_ticket_usd",
    "below_min": "below_min",
    "below min": "below_min",
    "min liquidity": "min_liquidity_usd",
    "min_liquidity": "min_liquidity_usd",
    "min_liquidity_usd": "min_liquidity_usd",
    "max top10": "max_top10_pct",
    "max_top10": "max_top10_pct",
    "max_top10_pct": "max_top10_pct",
    "poll": "scanner_poll_s",
    "scanner poll": "scanner_poll_s",
    "risk poll": "risk_poll_s",
    "min pool age": "min_pool_age_min",
    "max wait": "max_wait_min",
    "max_dev": "max_dev_pct",
    "max_dev_pct": "max_dev_pct",
    "lp locked": "min_lp_locked_pct",
    "min_lp_locked_pct": "min_lp_locked_pct",
    "max bundled": "max_bundled",
    "max_bundled": "max_bundled",
    "max delegated": "max_delegated_accounts",
    "max_delegated_accounts": "max_delegated_accounts",
    "min score": "min_score",
    "min_score": "min_score",
    "min alive": "min_alive_6h",
    "min_alive_6h": "min_alive_6h",
    "min organic": "min_organic",
    "min_organic": "min_organic",
    "max chase": "max_chase",
    "max_chase": "max_chase",
    "mode": "mode",
    "notifier": "notifier",
    "rpc": "rpc_url",
    "rpc_url": "rpc_url",
    "push_rejects": "push_rejects",
    "report_time": "report_time",
    "report time": "report_time",
    "fees_ref_discount": "fees_ref_discount",
    "fomo_handle": "fomo_handle",
    "analyst_mode": "analyst_mode",
    "analyst mode": "analyst_mode",
    "paper_start_stack": "paper_start_stack",
    "max_pool_pct": "max_pool_pct",
    "max pool": "max_pool_pct",
}


def fresh() -> dict[str, Any]:
    return deepcopy(DEFAULTS)


def min_stack(s: dict[str, Any]) -> float:
    pct = float(s["stack_pct"]) / 100.0
    if pct <= 0:
        return float("inf")
    return float(s["min_ticket_usd"]) / pct


def ticket_check(s: dict[str, Any], stack: float | None = None) -> dict[str, Any]:
    """Run the STEP 10 ticket check. Returns a message for the owner if needed."""
    st = float(stack if stack is not None else (
        s["paper_balance"] if s.get("mode") == "PAPER" else (s.get("live_stack") or s["paper_start_stack"])
    ))
    need = min_stack(s)
    min_t = float(s["min_ticket_usd"])
    pct = float(s["stack_pct"])
    below = s.get("below_min", "bump")
    if st + 1e-9 >= need:
        return {"ok": True, "warning": None, "block": False, "stack": st, "min_stack": need}
    if below == "bump":
        effective_pct = (min_t / st) * 100.0 if st else 0.0
        msg = f"tickets bumped to ${min_t:.2f} = {effective_pct:.2f}% of stack"
        return {"ok": True, "warning": msg, "block": False, "stack": st, "min_stack": need, "bumped": True}
    msg = f"every coin will be skipped, stack under ${need:.2f}"
    return {"ok": False, "warning": msg, "block": True, "stack": st, "min_stack": need, "bumped": False}


def resolve_alias(name: str) -> str | None:
    key = name.strip().lower().replace("-", "_")
    key = " ".join(key.split())
    if key in ALIASES:
        return ALIASES[key]
    # allow exact setting keys
    if name in DEFAULTS:
        return name
    compact = key.replace(" ", "_")
    if compact in DEFAULTS:
        return compact
    if compact in ALIASES:
        return ALIASES[compact]
    return None


def parse_value(key: str, raw: str) -> Any:
    s = raw.strip()
    if key in CHOICES:
        if key == "mode":
            return s.upper()
        return s.lower()
    if key == "report_time":
        return s
    if key == "rpc_url":
        return s
    if key == "fomo_handle":
        return s.lstrip("@")
    if key == "auditor_enabled" or key == "push_rejects":
        v = s.lower()
        if v in {"1", "true", "yes", "on"}:
            return True
        if v in {"0", "false", "no", "off"}:
            return False
        raise ValueError("use true or false")
    # percents may be written as -8% or 8%
    t = s.replace("%", "").replace(",", "")
    if t.startswith("+"):
        t = t[1:]
    if t.startswith("-") and key in {"stop_pct"}:
        t = t[1:]
    if key in {"scanner_poll_s", "min_pool_age_min", "max_wait_min", "max_bundled",
               "max_delegated_accounts", "auditor_retries", "min_score",
               "analyst_timeout_s", "bundled_penalty_at",
               "executor_confirm_window_min", "risk_poll_s", "risk_confirm_window_min"}:
        return int(float(t))
    return float(t)


def validate(key: str, value: Any) -> str | None:
    """Return an error string if out of range, else None."""
    if key in CHOICES:
        allowed = CHOICES[key]
        if key == "mode" and value not in allowed:
            return f"{key} must be {' or '.join(allowed)}"
        if value not in allowed:
            return f"{key} must be one of: {', '.join(allowed)}"
        return None
    if key not in RANGES:
        return None
    lo, hi = RANGES[key]
    try:
        v = float(value)
    except (TypeError, ValueError):
        return f"{key} must be a number"
    if lo is not None and v < lo:
        return f"{key} out of range ({lo}–{hi})"
    if hi is not None and v > hi:
        return f"{key} out of range ({lo}–{hi})"
    return None


def format_change(key: str, old: Any, new: Any) -> str:
    if key == "stop_pct":
        return f"stop -{old}% -> -{new}%"
    return f"{key} {old} -> {new}"
