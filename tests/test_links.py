"""Acceptance 1: exact FOMO URL format with r=olli81; unknown chain -> SIGNUP_URL; no old referral code."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from links import SIGNUP_URL, CHAIN_ID, coin_url, profile_url, REF

FAIL = 0

def check(cond, msg):
    global FAIL
    if cond:
        print("  PASS", msg)
    else:
        print("  FAIL", msg)
        FAIL += 1


def test_urls():
    print("test_links")
    check(SIGNUP_URL == "https://fomo.family/r/olli81", f"SIGNUP_URL={SIGNUP_URL}")
    check(CHAIN_ID == {"solana": 1399811149, "robinhood": 4663, "base": 8453, "bnb": 56}, f"CHAIN_ID={CHAIN_ID}")
    mint = "So11111111111111111111111111111111111111112"
    u = coin_url(mint, "solana")
    expect = (
        f"https://fomo.family/coin?address={mint}"
        f"&chainId=1399811149&r=olli81&source=share_link"
    )
    check(u == expect, u)
    check(coin_url(mint, "base") == (
        f"https://fomo.family/coin?address={mint}&chainId=8453&r=olli81&source=share_link"
    ), "base chainId 8453")
    check(coin_url("0xabc", "unknown-chain") == SIGNUP_URL, "unknown chain -> SIGNUP_URL")
    check(coin_url(None, "solana") == SIGNUP_URL, "missing address -> SIGNUP_URL")
    p = profile_url("olli81")
    check(p == "https://fomo.family/profile/olli81?source=share_link&r=olli81", p)
    check(("savi"+"pww") not in u and ("savi"+"pww") not in p, "no old referral code")
    for url in (SIGNUP_URL, u, p):
        check("bit.ly" not in url and "t.co" not in url and "tinyurl" not in url, f"not shortened: {url}")
        check("https://fomo.family/" in url, f"direct fomo.family: {url}")


def grep_repo():
    needle = "savi" + "pww"
    r = subprocess.run(
        ["rg", "-n", "--fixed-strings", needle, str(ROOT),
         "--glob", "!.git/**", "--glob", "!.venv/**", "--glob", "!logs/**", "--glob", "!data/**"],
        capture_output=True, text=True,
    )
    check(r.returncode != 0 and not (r.stdout or "").strip(), "no old referral code anywhere in source")
    url_re = re.compile(r"https://fomo\.family/[^\s\"')]+")
    bad = []
    stale = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith((".git/", ".venv/", "logs/", "data/", "screens/", "docs/d/")):
            continue
        if path.suffix not in {".py", ".js", ".html", ".md", ".css", ".json"}:
            continue
        try:
            text = path.read_text()
        except Exception:
            continue
        for m in url_re.finditer(text):
            url = m.group(0).rstrip(".,);")
            # f-string templates are not concrete URLs
            if "{" in url:
                continue
            if "r=olli81" in url or "/r/olli81" in url:
                if "/tokens/" in url and rel not in {"tests/test_links.py"}:
                    stale.append(f"{rel}: {url}")
                continue
            if url.rstrip("/") == "https://fomo.family":
                continue
            bad.append(f"{rel}: {url}")
    check(not bad, "all concrete FOMO URLs in source carry r=olli81" + (("\n    " + "\n    ".join(bad)) if bad else ""))
    check(not stale, "no leftover /tokens/ FOMO paths" + (("\n    " + "\n    ".join(stale)) if stale else ""))


if __name__ == "__main__":
    test_urls()
    grep_repo()
    sys.exit(1 if FAIL else 0)
