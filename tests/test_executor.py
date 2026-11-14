"""Executor: Brain supplies size; rechecks and ticket check on a $50 stack."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agents.executor import recheck, execution_payload
import settings as S
from links import coin_url

FAIL = 0

def check(cond, msg):
    global FAIL
    print(("  PASS " if cond else "  FAIL ") + msg)
    if not cond:
        FAIL += 1


def main():
    print("test_executor")
    s = S.fresh()
    check(abs(float(s["min_ticket_usd"]) - 5) < 1e-9, f"default min_ticket_usd is 5 ({s['min_ticket_usd']})")
    check(abs(float(s["paper_start_stack"]) - 50) < 1e-9, f"default paper_start_stack is 50 ({s['paper_start_stack']})")

    # $50 stack must not warn now that Brain sizes $5–$10
    chk = S.ticket_check(s, 50)
    check(chk["ok"] and not chk.get("warning") and not chk.get("block"), f"$50 stack is clean {chk}")

    chk200 = S.ticket_check(dict(s, paper_balance=200, mode="PAPER"), 200)
    check(chk200["ok"] and not chk200.get("warning"), f"$200 also clean {chk200}")

    # under Brain's min size, skip every coin
    chk_lo = S.ticket_check(s, 4)
    check(chk_lo["block"] and "every coin will be skipped" in (chk_lo["warning"] or "") and "4" not in "keep", f"stack $4 blocks {chk_lo}")
    check("5.00" in chk_lo["warning"] or "5" in chk_lo["warning"], f"warning names the $5 floor {chk_lo}")

    # rechecks still belong to the executor
    fresh_run = {"priceUsd": 1.16, "liquidity_usd": 50_000}
    check(recheck(1.0, 50_000, fresh_run, s) == "price ran", "price +16% is 'price ran'")
    fresh_ok = {"priceUsd": 1.10, "liquidity_usd": 50_000}
    check(recheck(1.0, 50_000, fresh_ok, s) is None, "price +10% is within the 15% run window")
    fresh_liq = {"priceUsd": 1.0, "liquidity_usd": 39_000}
    check(recheck(1.0, 50_000, fresh_liq, s) == "liquidity dropped", "liq -22% is 'liquidity dropped'")

    # payload takes Brain's size as-is (executor does not bump)
    pl = execution_payload("mint", 1.0, 7.5, 50, coin_url("mint", "solana"), "PAPER", "sent")
    check(abs(pl["sizeUsd"] - 7.5) < 1e-9 and abs(pl["stackPct"] - 15) < 1e-9, f"payload keeps Brain size {pl}")


if __name__ == "__main__":
    main()
    sys.exit(1 if FAIL else 0)
