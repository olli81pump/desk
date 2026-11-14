"""Acceptance 1b: PAPER push payload carries the exact links.py URL with r=olli81.

The actual Telegram send happens once at the end of STEP 13 (marked as test).
This test builds the same message + keyboard the desk uses and checks the URL.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from links import coin_url
from notify import paper, buy_keyboard

MINT = "So11111111111111111111111111111111111111112"


def main() -> int:
    print("test_notify")
    text = paper("TEST · Desk is live")
    assert text.startswith("PAPER · "), text
    kb = buy_keyboard(MINT)
    url = kb["inline_keyboard"][0][0]["url"]
    expect = coin_url(MINT, "solana")
    assert url == expect, (url, expect)
    assert "r=olli81" in url
    assert ("savi"+"pww") not in url
    print("  PASS payload", text, url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
