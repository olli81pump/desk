"""FOMO URLs. Every URL carries r=olli81. Never shorten or redirect."""

from __future__ import annotations

import logging

log = logging.getLogger("links")

REF = "olli81"
CHAIN_ID = {"solana": 1399811149, "robinhood": 4663, "base": 8453, "bnb": 56}
SIGNUP_URL = "https://fomo.family/r/olli81"

_CHAIN_ALIAS = {"bsc": "bnb"}


def coin_url(address: str | None, chain: str = "solana") -> str:
    """Direct FOMO coin URL, or SIGNUP_URL when the chain is unknown."""
    slug = str(chain or "").strip().lower()
    slug = _CHAIN_ALIAS.get(slug, slug)
    if slug not in CHAIN_ID:
        log.warning("unknown FOMO chain %r; falling back to signup", chain)
        return SIGNUP_URL
    if not address:
        return SIGNUP_URL
    return f"https://fomo.family/coin?address={address}&chainId={CHAIN_ID[slug]}&r={REF}&source=share_link"


def profile_url(handle: str | None = None) -> str:
    h = (handle or REF).lstrip("@")
    return f"https://fomo.family/profile/{h}?source=share_link&r={REF}"


def invite_url() -> str:
    return SIGNUP_URL
