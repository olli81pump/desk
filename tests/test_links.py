"""Acceptance 1: every FOMO URL carries r=olli81; unknown chain -> SIGNUP_URL; no old referral code; no short links."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from links import SIGNUP_URL, coin_url, profile_url, REF

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
    u = coin_url("So11111111111111111111111111111111111111112", "solana")
    check("/tokens/solana/" in u and u.startswith("https://fomo.family/"), u)
    check("r=olli81" in u, "coin_url has r=olli81")
    check(("savi"+"pww") not in u, "no old referral code in coin_url")
    check(coin_url("0xabc", "unknown-chain") == SIGNUP_URL, "unknown chain -> SIGNUP_URL")
    check(coin_url(None, "solana") == SIGNUP_URL, "missing mint -> SIGNUP_URL")
    p = profile_url("olli81")
    check("r=olli81" in p and "/profile/olli81" in p and p.startswith("https://"), p)
    # no shorteners
    for url in (SIGNUP_URL, u, p):
        check("bit.ly" not in url and "t.co" not in url and "tinyurl" not in url, f"not shortened: {url}")
        check("https://fomo.family/" in url, f"direct fomo.family: {url}")



def grep_repo():
    import re
    needle = "savi" + "pww"
    r = subprocess.run(
        ["rg", "-n", "--fixed-strings", needle, str(ROOT),
         "--glob", "!.git/**", "--glob", "!.venv/**", "--glob", "!logs/**", "--glob", "!data/**"],
        capture_output=True, text=True,
    )
    check(r.returncode != 0 and not (r.stdout or "").strip(), "no old referral code anywhere in source")
    url_re = re.compile(r"https://fomo\.family/[^\s\"')]+")
    bad = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith((".git/", ".venv/", "logs/", "data/", "screens/")):
            continue
        if path.suffix not in {".py", ".js", ".html", ".md", ".css", ".json"}:
            continue
        try:
            text = path.read_text()
        except Exception:
            continue
        for m in url_re.finditer(text):
            url = m.group(0).rstrip(".,);")
            if "r=olli81" in url or "/r/olli81" in url:
                continue
            # host-only constant
            if url.rstrip("/") == "https://fomo.family":
                continue
            bad.append(f"{rel}: {url}")
    check(not bad, "all concrete FOMO URLs in source carry r=olli81" + (("\n    " + "\n    ".join(bad)) if bad else ""))


if __name__ == "__main__":
    test_urls()
    grep_repo()
    sys.exit(1 if FAIL else 0)
