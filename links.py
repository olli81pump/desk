"""FOMO URLs. Every URL carries r=olli81. Never shorten or redirect."""

from __future__ import annotations

REF = "olli81"
FOMO_HOST = "https://fomo.family"
SIGNUP_URL = f"{FOMO_HOST}/r/{REF}"

# Chains FOMO actually routes under /tokens/{chain}/...
KNOWN_CHAINS = {
    "solana",
    "base",
    "ethereum",
    "bnb",
    "bsc",
    "monad",
    "hyperliquid",
    "robinhood",
}

_CHAIN_ALIAS = {"bsc": "bnb"}


def _chain_slug(chain: str | None) -> str | None:
    if not chain:
        return None
    slug = str(chain).strip().lower()
    slug = _CHAIN_ALIAS.get(slug, slug)
    if slug not in KNOWN_CHAINS:
        return None
    return slug


def coin_url(mint: str | None, chain: str = "solana") -> str:
    """Direct FOMO token URL, or SIGNUP_URL when the chain is unknown."""
    slug = _chain_slug(chain)
    if not slug or not mint:
        return SIGNUP_URL
    return f"{FOMO_HOST}/tokens/{slug}/{mint}?r={REF}"


def profile_url(handle: str | None = None) -> str:
    h = (handle or REF).lstrip("@")
    return f"{FOMO_HOST}/profile/{h}?r={REF}"


def invite_url() -> str:
    return SIGNUP_URL
