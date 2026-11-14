"""Solana JSON-RPC helpers. Read-only: never signs or sends transactions."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import aiohttp
from solders.pubkey import Pubkey

TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
PUMPFUN_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"

DEFAULT_RPC = "https://api.mainnet-beta.solana.com"


def bonding_curve_pda(mint: str) -> str | None:
    try:
        mint_pk = Pubkey.from_string(mint)
        prog = Pubkey.from_string(PUMPFUN_PROGRAM)
        pda, _ = Pubkey.find_program_address([b"bonding-curve", bytes(mint_pk)], prog)
        return str(pda)
    except Exception:
        return None


class Rpc:
    def __init__(self, url: str = DEFAULT_RPC, session: aiohttp.ClientSession | None = None):
        self.url = url
        self._session = session
        self._own_session = False

    async def _sess(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
            self._own_session = True
        return self._session

    async def close(self) -> None:
        if self._own_session and self._session and not self._session.closed:
            await self._session.close()

    async def call(self, method: str, params: list, timeout: float = 30.0) -> Any:
        sess = await self._sess()
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        async with sess.post(self.url, json=payload, timeout=timeout) as r:
            data = await r.json()
        if "error" in data:
            raise RuntimeError(f"rpc {method}: {data['error']}")
        return data.get("result")

    async def get_account_info(self, pubkey: str, retries: int = 3) -> dict | None:
        last = None
        for i in range(retries):
            try:
                res = await self.call("getAccountInfo", [pubkey, {"encoding": "jsonParsed"}])
                return (res or {}).get("value")
            except Exception as e:
                last = e
                await asyncio.sleep(2)
        if last:
            raise last
        return None

    async def get_token_supply(self, mint: str) -> tuple[float | None, int | None]:
        res = await self.call("getTokenSupply", [mint])
        val = (res or {}).get("value") or {}
        try:
            return float(val.get("uiAmount")), int(val.get("decimals") or 0)
        except (TypeError, ValueError):
            return None, None

    async def get_token_largest(self, mint: str) -> list[dict]:
        res = await self.call("getTokenLargestAccounts", [mint])
        return list((res or {}).get("value") or [])

    async def token_accounts_by_owner(self, owner: str, mint: str) -> list[dict]:
        out = []
        for program in (TOKEN_PROGRAM, TOKEN_2022_PROGRAM):
            try:
                res = await self.call(
                    "getTokenAccountsByOwner",
                    [owner, {"mint": mint, "programId": program}, {"encoding": "jsonParsed"}],
                )
                out.extend((res or {}).get("value") or [])
            except Exception:
                continue
        return out

    async def owner_balance_ui(self, owner: str, mint: str) -> float:
        accs = await self.token_accounts_by_owner(owner, mint)
        total = 0.0
        for a in accs:
            info = (((a.get("account") or {}).get("data") or {}).get("parsed") or {}).get("info") or {}
            amt = (info.get("tokenAmount") or {}).get("uiAmount")
            try:
                total += float(amt or 0)
            except (TypeError, ValueError):
                pass
        return total

    async def get_program_accounts_for_mint(self, mint: str, timeout: float = 60.0) -> list[dict]:
        """Layer 8: Token (dataSize 165 + memcmp) AND Token-2022 (memcmp only)."""
        accs: list[dict] = []
        # legacy
        try:
            res = await self.call(
                "getProgramAccounts",
                [
                    TOKEN_PROGRAM,
                    {
                        "encoding": "jsonParsed",
                        "commitment": "confirmed",
                        "filters": [
                            {"dataSize": 165},
                            {"memcmp": {"offset": 0, "bytes": mint}},
                        ],
                    },
                ],
                timeout=timeout,
            )
            accs.extend(res or [])
        except Exception:
            pass
        try:
            res = await self.call(
                "getProgramAccounts",
                [
                    TOKEN_2022_PROGRAM,
                    {
                        "encoding": "jsonParsed",
                        "commitment": "confirmed",
                        "filters": [{"memcmp": {"offset": 0, "bytes": mint}}],
                    },
                ],
                timeout=timeout,
            )
            accs.extend(res or [])
        except Exception:
            # surface as empty so auditor can red "no data: delegations"
            if not accs:
                raise
        return accs


def mint_authorities_from_account(value: dict | None) -> dict:
    if not value:
        return {"mintAuthority": None, "freezeAuthority": None, "supply": None, "decimals": None, "ok": False}
    info = (((value.get("data") or {}).get("parsed") or {}).get("info") or {})
    return {
        "mintAuthority": info.get("mintAuthority"),
        "freezeAuthority": info.get("freezeAuthority"),
        "supply": info.get("supply"),
        "decimals": info.get("decimals"),
        "ok": True,
        "owner": value.get("owner"),
    }


def parsed_token_info(gpa_item: dict) -> dict:
    return (((gpa_item.get("account") or {}).get("data") or {}).get("parsed") or {}).get("info") or {}
