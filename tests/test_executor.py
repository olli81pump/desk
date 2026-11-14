"""Acceptance 4: sizing bump/skip, ticket warning, pool cap."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agents.executor import size_position
import settings as S

FAIL = 0

def check(cond, msg):
    global FAIL
    print(("  PASS " if cond else "  FAIL ") + msg)
    if not cond:
        FAIL += 1


def main():
    print("test_executor")
    s = S.fresh()
    s["stack_pct"] = 8
    s["min_ticket_usd"] = 47.50
    s["below_min"] = "bump"
    r = size_position(200, None, s)
    # 8% of 200 = 16 -> bump to 47.50
    check(abs(r["raw"] - 16) < 1e-9, f"raw 8% of $200 = $16 ({r['raw']})")
    check(r["bumped"] and abs(r["size"] - 47.50) < 1e-9 and not r["skipped"], f"bump sends $47.50 {r}")

    s2 = dict(s, below_min="skip")
    r2 = size_position(200, None, s2)
    check(r2["skipped"] and r2["size"] == 0, f"skip skips {r2}")

    # PAPER start at $200 with skip -> every coin will be skipped warning
    s3 = dict(s, below_min="skip", paper_balance=200, mode="PAPER")
    chk = S.ticket_check(s3, 200)
    check(chk["block"] and "every coin will be skipped" in chk["warning"] and "593.75" in chk["warning"], chk["warning"])

    # bump warning at start
    chk2 = S.ticket_check(dict(s, below_min="bump", paper_balance=200, mode="PAPER"), 200)
    check(chk2["ok"] and chk2.get("bumped") and "tickets bumped to $47.50" in chk2["warning"], chk2["warning"])

    # pool liquidity $40,000 caps any size at $800
    s4 = dict(s, stack_pct=8, below_min="bump")
    # huge stack so 8% would be > 800
    r4 = size_position(100_000, 40_000, s4)
    check(abs(r4["size"] - 800) < 1e-9, f"liq $40k caps at $800 ({r4})")


if __name__ == "__main__":
    main()
    sys.exit(1 if FAIL else 0)
