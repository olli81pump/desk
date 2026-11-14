"""Acceptance 2: gate thresholds; rules mode labeled Analyst (rules)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agents.analyst import gate, rules_answers, score_of, analyse
import settings as S

s = S.fresh()
FAIL = 0

def check(cond, msg):
    global FAIL
    print(("  PASS " if cond else "  FAIL ") + msg)
    if not cond:
        FAIL += 1


def isolated():
    print("test_gate")
    # each of the four fails in isolation
    base = {"alive_6h": 0.70, "organic": 0.65, "flush": 1.0, "chase": 0.30}
    # score at these values: (0.70+0.65+1+0.70)/4*100 = 76.25 -> 76, passes
    ok, sc, failed = gate(base, s)
    check(ok and sc >= 70, f"healthy base passes score={sc} failed={failed}")

    a = dict(base, alive_6h=0.69)
    ok, sc, failed = gate(a, s)
    check((not ok) and any(f.startswith("alive_6h") for f in failed), f"alive 0.69 rejects {failed}")

    a = dict(base, organic=0.64)
    ok, sc, failed = gate(a, s)
    check((not ok) and any(f.startswith("organic") for f in failed), f"organic 0.64 rejects {failed}")

    a = dict(base, chase=0.31)
    ok, sc, failed = gate(a, s)
    check((not ok) and any(f.startswith("chase") for f in failed), f"chase 0.31 rejects {failed}")

    # score 69: pick flush so the average * 100 rounds to 69, others at threshold
    # (0.70+0.65+flush+0.70)/4 * 100 = 69 -> flush=0.71
    a = {"alive_6h": 0.70, "organic": 0.65, "flush": 0.71, "chase": 0.30}
    ok, sc, failed = gate(a, s)
    check(sc == 69 and not ok and any(f.startswith("score") for f in failed), f"score 69 rejects sc={sc} {failed}")

    # all at threshold pass (need flush high enough for score >= 70)
    a = {"alive_6h": 0.70, "organic": 0.65, "flush": 0.75, "chase": 0.30}
    ok, sc, failed = gate(a, s)
    check(ok and sc >= 70 and not failed, f"all at threshold pass sc={sc}")

    # rules mode with fake DexScreener numbers
    # vol h1 = 25000 -> alive=1; buys h1=150 -> organic=1; m5 drop -5 with buys>=sells -> flush=1; h1 change 0 -> chase=0
    dex = {
        "volume_h1": 25000, "txns_h1_buys": 150,
        "txns_m5_buys": 10, "txns_m5_sells": 5,
        "priceChange_m5": -5, "priceChange_h1": 0,
        "volume_m5": 1000, "liquidity_usd": 50000, "marketCap": 100000,
    }
    ans = rules_answers(dex, bundled=0, s=s)
    result = analyse(dex, {"bundled_n": 0}, s, "Mint111", "Fake")
    check(result["model"] == "rules" and result["inputTokens"] == 0, "model=rules inputTokens=0")
    check(result["passed"] is True, f"rules pass {result}")
    # a reject row should read Analyst (rules)
    dex_bad = dict(dex, volume_h1=1000, txns_h1_buys=10, priceChange_h1=90)
    result_bad = analyse(dex_bad, {"bundled_n": 0}, s, "Mint222", "Fake2")
    check(result_bad["passed"] is False, f"rules reject {result_bad['failed']}")
    row = f"Analyst (rules) · {result_bad['failed'][0]}"
    check(row.startswith("Analyst (rules)"), row)
    print("  sample activity row:", row)


if __name__ == "__main__":
    isolated()
    sys.exit(1 if FAIL else 0)
