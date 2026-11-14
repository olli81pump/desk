"""DexScreener and RugCheck (read-only HTTP)."""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

from fields import (
    dex_fields,
    graph_has_edges_key,
    graph_networks,
    rugcheck_creator,
    rugcheck_lp_locked_pct,
    rugcheck_market_for_pool,
)

DEX_TOKENS = "https://api.dexscreener.com/tokens/v1/solana/{mints}"
RUG_REPORT = "https://api.rugcheck.xyz/v1/tokens/{mint}/report"
RUG_GRAPH = "https://api.rugcheck.xyz/v1/tokens/{mint}/insiders/graph"


class RateLimiter:
    def __init__(self, max_per_min: int = 250):
        self.max = max_per_min
        self._hits: list[float] = []
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = asyncio.get_event_loop().time()
            self._hits = [t for t in self._hits if now - t < 60]
            if len(self._hits) >= self.max:
                delay = 60 - (now - self._hits[0]) + 0.05
                await asyncio.sleep(max(delay, 0))
            self._hits.append(asyncio.get_event_loop().time())


class HttpSources:
    def __init__(self, session: aiohttp.ClientSession | None = None):
        self._session = session
        self._own = False
        self.dex_limit = RateLimiter(250)
        self._429_until = 0.0

    async def _sess(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=25))
            self._own = True
        return self._session

    async def close(self) -> None:
        if self._own and self._session and not self._session.closed:
            await self._session.close()

    async def _get_json(self, url: str, retries: int = 3) -> Any:
        sess = await self._sess()
        last = None
        for i in range(retries):
            try:
                async with sess.get(url, headers={"User-Agent": "grok-bot-desk/1.0"}) as r:
                    if r.status == 429:
                        await asyncio.sleep(30)
                        last = RuntimeError("429")
                        continue
                    if r.status >= 400:
                        last = RuntimeError(f"HTTP {r.status} {url}")
                        await asyncio.sleep(1 + i)
                        continue
                    return await r.json()
            except Exception as e:
                last = e
                await asyncio.sleep(1 + i)
        if last:
            raise last
        return None

    async def dexscreener(self, mints: list[str]) -> dict[str, dict]:
        """Batch DexScreener; return mint -> fields for the PumpSwap pair (most liquid)."""
        out: dict[str, dict] = {}
        if not mints:
            return out
        # DexScreener accepts comma-separated mints; keep batches modest
        chunks = [mints[i:i + 20] for i in range(0, len(mints), 20)]
        for chunk in chunks:
            await self.dex_limit.wait()
            url = DEX_TOKENS.format(mints=",".join(chunk))
            try:
                body = await self._get_json(url)
            except Exception:
                continue
            pairs_by_mint: dict[str, list] = {}
            rows = body if isinstance(body, list) else []
            for p in rows:
                if not isinstance(p, dict):
                    continue
                mint = ((p.get("baseToken") or {}).get("address")) or ""
                pairs_by_mint.setdefault(mint, []).append(p)
            for mint, plist in pairs_by_mint.items():
                fields = dex_fields(plist)
                if fields:
                    out[mint] = fields
        return out

    async def rug_report(self, mint: str) -> dict | None:
        try:
            body = await self._get_json(RUG_REPORT.format(mint=mint))
            return body if isinstance(body, dict) else None
        except Exception:
            return None

    async def rug_graph(self, mint: str) -> Any:
        try:
            return await self._get_json(RUG_GRAPH.format(mint=mint))
        except Exception:
            return None


# re-export mapping helpers for agents
__all__ = [
    "HttpSources",
    "dex_fields",
    "rugcheck_creator",
    "rugcheck_market_for_pool",
    "rugcheck_lp_locked_pct",
    "graph_has_edges_key",
    "graph_networks",
]
