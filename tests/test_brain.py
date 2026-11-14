"""Brain sizing: score 70->$5, 100->$10, pool cap, free cap, skip under $5."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agents.brain import size_buy
import settings as S

FAIL = 0

def check(cond, msg):
    global FAIL
    print(("  PASS " if cond else "  FAIL ") + msg)
    if not cond:
        FAIL += 1


def main():
    print("test_brain")
    s = S.fresh()
    r70 = size_buy(70, 100_000, 50, 50, s, mint="m")
    check(r70["agent"] == "brain" and not r70["skipped"] and abs(r70["sizeUsd"] - 5) < 1e-9, f"score 70 -> $5 {r70}")
    r100 = size_buy(100, 100_000, 50, 50, s, mint="m")
    check(not r100["skipped"] and abs(r100["sizeUsd"] - 10) < 1e-9, f"score 100 -> $10 {r100}")
    r85 = size_buy(85, 100_000, 50, 50, s, mint="m")
    check(abs(r85["sizeUsd"] - 7.5) < 1e-9, f"score 85 -> $7.50 {r85}")

    # pool cap: liq $300, 2% = $6, score 100 would be $10 -> $6, capHit max_pool_pct
    rpool = size_buy(100, 300, 50, 50, s, mint="m")
    check(abs(rpool["sizeUsd"] - 6) < 1e-9 and rpool["capHit"] == "max_pool_pct" and not rpool["skipped"], f"pool cap $6 {rpool}")

    # pool cap under $5: liq $200, 2% = $4 -> skip
    rskip = size_buy(100, 200, 50, 50, s, mint="m")
    check(rskip["skipped"] and rskip["sizeUsd"] == 0 and rskip["capHit"] == "max_pool_pct" and rskip["reason"], f"pool cap skip under $5 {rskip}")

    # free cap: score 100, free $7 -> $7
    rfree = size_buy(100, 100_000, 50, 7, s, mint="m")
    check(abs(rfree["sizeUsd"] - 7) < 1e-9 and rfree["capHit"] == "free_stack" and not rfree["skipped"], f"free cap $7 {rfree}")

    # free cap under $5: free $4 -> skip
    rfreeskip = size_buy(100, 100_000, 50, 4, s, mint="m")
    check(rfreeskip["skipped"] and rfreeskip["sizeUsd"] == 0 and rfreeskip["capHit"] == "free_stack", f"free cap skip under $5 {rfreeskip}")

    # JSON shape
    for k in ("agent", "mint", "score", "sizeUsd", "stackPct", "capHit", "reason"):
        check(k in r70, f"output has {k}")


if __name__ == "__main__":
    main()
    sys.exit(1 if FAIL else 0)
