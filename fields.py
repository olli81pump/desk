"""STEP 2 field mapping.

Every path below was read from a raw sample in logs/raw/. A value of None
means that key was not present in the sample. Nothing here is guessed.

Samples
-------
PumpPortal migration
    logs/raw/pumpportal_migration.json
    live event, 2026-11-14 ~07:57 UTC
    mint FaudEpeLJrPbMw9VWG1mq5qRBLv9AjSXVMBLZg7ipump
    keys: signature, mint, txType, pool
    Note: pool == "pump-amm" (a kind tag), not a base58 pool address.
    creator is absent.

DexScreener pair
    logs/raw/dexscreener_pair.json
    GET https://api.dexscreener.com/tokens/v1/solana/{mint}
    body is a JSON array of pair objects (not {"pairs": [...]})
    mint 4CxjZyMNoF1p6eXHXHv1TWpS2X47CuUmLwtGe18spump (mihao)
    one pair, dexId == "pumpswap"
    A second live-migration fetch is in dexscreener_pair_live_migration.json
    (APPLE, same array shape, dexId pumpswap).

RugCheck report
    logs/raw/rugcheck_report.json
    GET https://api.rugcheck.xyz/v1/tokens/{mint}/report
    same mihao mint.
    markets have no key named "pool"; the pool address is markets[].pubkey.
    The PumpSwap pool is the market whose pubkey equals DexScreener pairAddress
    (marketType was "pump_fun_amm" in this sample).
    LP locked percent is markets[].lp.lpLockedPct.
    No key named burned / lpBurned / burnedPct was present.

RugCheck insiders graph
    logs/raw/rugcheck_insiders_graph.json
    GET https://api.rugcheck.xyz/v1/tokens/{mint}/insiders/graph
    body is a JSON array of networks, not a single {nodes, edges} object.
    Each item has nodes and links (not edges). edges is absent.

RPC getAccountInfo (jsonParsed)
    logs/raw/rpc_getaccountinfo_mint.json
    mint owner was Token-2022 (program "spl-token-2022").
    The parsed info path is the same as a classic spl-token mint.
    A live-migration mint sample is in rpc_getaccountinfo_live_migration.json
    (also Token-2022, same paths, mintAuthority and freezeAuthority null).

RPC getProgramAccounts (layer 8)
    logs/raw/layer8_account_samples.json
    Token-2022 token-account jsonParsed info.
    "delegate" and "delegatedAmount" are present only when a delegate is set;
    they are omitted (not null) on accounts with no delegate.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

# Official program ids (Token-2022 verified against solana-program.com docs).
TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"

# ---------------------------------------------------------------------------
# Exact key paths as they appear in the raw JSON. None = not present.
# ---------------------------------------------------------------------------

MIGRATION_FIELDS: dict[str, Optional[str]] = {
    "mint": "mint",
    "signature": "signature",
    "txType": "txType",
    # Present, but the sample value is the tag "pump-amm", not a base58 address.
    "pool": "pool",
    "creator": None,
}

# DexScreener: body is a list. Paths are relative to one pair object.
# Choose the PumpSwap pair (dexId == "pumpswap"); if several, the one with
# the highest liquidity.usd.
DEX_FIELDS: dict[str, Optional[str]] = {
    "pairAddress": "pairAddress",
    "dexId": "dexId",
    "priceUsd": "priceUsd",  # string in the sample, e.g. "0.01682"
    "liquidity.usd": "liquidity.usd",
    "marketCap": "marketCap",
    "volume.m5": "volume.m5",
    "volume.h1": "volume.h1",
    "volume.h24": "volume.h24",
    "txns.m5.buys": "txns.m5.buys",
    "txns.m5.sells": "txns.m5.sells",
    "txns.h1.buys": "txns.h1.buys",
    "txns.h1.sells": "txns.h1.sells",
    "priceChange.m5": "priceChange.m5",
    "priceChange.h1": "priceChange.h1",
    "priceChange.h24": "priceChange.h24",
    "pairCreatedAt": "pairCreatedAt",  # epoch milliseconds
    "baseToken.address": "baseToken.address",
    "baseToken.name": "baseToken.name",
    "baseToken.symbol": "baseToken.symbol",
}

RUGCHECK_REPORT_FIELDS: dict[str, Optional[str]] = {
    "creator": "creator",
    "creatorBalance": "creatorBalance",
    "mint": "mint",
    # No markets[].pool key. The pool address is markets[].pubkey.
    "markets[].pool": None,
    "markets[].pubkey": "markets[].pubkey",
    "markets[].marketType": "markets[].marketType",
    "markets[].lp.lpLockedPct": "markets[].lp.lpLockedPct",
    "markets[].lp.lpLocked": "markets[].lp.lpLocked",
    "markets[].lp.lpUnlocked": "markets[].lp.lpUnlocked",
    "markets[].lp.lpLockedUSD": "markets[].lp.lpLockedUSD",
    # No burned-percent key in the sample.
    "markets[].lp.burnedPct": None,
    "markets[].lp.lpBurned": None,
    "mintAuthority": "mintAuthority",
    "freezeAuthority": "freezeAuthority",
}

# Graph body is a list of networks.
RUGCHECK_GRAPH_FIELDS: dict[str, Optional[str]] = {
    "nodes": "[].nodes",
    "nodes[].id": "[].nodes[].id",
    "nodes[].holdings": "[].nodes[].holdings",
    "nodes[].participant": "[].nodes[].participant",
    "edges": None,  # not present; do not treat as links
    "links": "[].links",  # {source, target}
    "links[].source": "[].links[].source",
    "links[].target": "[].links[].target",
    "network_type": "[].network_type",
}

RPC_MINT_FIELDS: dict[str, Optional[str]] = {
    "mintAuthority": "result.value.data.parsed.info.mintAuthority",
    "freezeAuthority": "result.value.data.parsed.info.freezeAuthority",
    "supply": "result.value.data.parsed.info.supply",  # string
    "decimals": "result.value.data.parsed.info.decimals",
    "isInitialized": "result.value.data.parsed.info.isInitialized",
    "program": "result.value.data.program",  # "spl-token-2022" in the sample
    "owner": "result.value.owner",
}

# Layer 8 token-account paths, relative to one getProgramAccounts result item.
RPC_TOKEN_ACCOUNT_FIELDS: dict[str, Optional[str]] = {
    "pubkey": "pubkey",
    "mint": "account.data.parsed.info.mint",
    "owner": "account.data.parsed.info.owner",
    "state": "account.data.parsed.info.state",
    "tokenAmount.amount": "account.data.parsed.info.tokenAmount.amount",
    "tokenAmount.uiAmount": "account.data.parsed.info.tokenAmount.uiAmount",
    # Present only when a delegate is set; omitted otherwise.
    "delegate": "account.data.parsed.info.delegate",
    "delegatedAmount": "account.data.parsed.info.delegatedAmount",
}


def dig(obj: Any, path: Optional[str], default: Any = None) -> Any:
    """Walk a dotted path. Returns default if any step is missing."""
    if not path or obj is None:
        return default
    cur = obj
    for part in path.split("."):
        if isinstance(cur, Mapping) and part in cur:
            cur = cur[part]
        else:
            return default
    return cur


def migration_fields(msg: Mapping[str, Any]) -> dict[str, Any]:
    """Extract scanner inputs from one PumpPortal migration message."""
    pool = msg.get("pool")
    return {
        "mint": msg.get("mint"),
        "signature": msg.get("signature"),
        "txType": msg.get("txType"),
        "pool": pool,
        # Not a base58 address in the live sample ("pump-amm").
        "pool_is_address": isinstance(pool, str) and 32 <= len(pool) <= 44 and pool != "pump-amm",
        "creator": msg.get("creator"),  # absent in the sample -> None
    }


def pumpswap_pair(dex_body: Any) -> Optional[dict[str, Any]]:
    """Pick the PumpSwap pair with the most liquidity.usd from a DexScreener list."""
    pairs = dex_body if isinstance(dex_body, list) else []
    pumps = [p for p in pairs if isinstance(p, dict) and p.get("dexId") == "pumpswap"]
    if not pumps:
        return None

    def liq(p: Mapping[str, Any]) -> float:
        usd = dig(p, "liquidity.usd")
        try:
            return float(usd)
        except (TypeError, ValueError):
            return 0.0

    return max(pumps, key=liq)


def dex_fields(dex_body: Any) -> Optional[dict[str, Any]]:
    pair = pumpswap_pair(dex_body)
    if pair is None:
        return None
    return {
        "pairAddress": pair.get("pairAddress"),
        "dexId": pair.get("dexId"),
        "priceUsd": pair.get("priceUsd"),
        "liquidity_usd": dig(pair, "liquidity.usd"),
        "marketCap": pair.get("marketCap"),
        "volume_m5": dig(pair, "volume.m5"),
        "volume_h1": dig(pair, "volume.h1"),
        "volume_h24": dig(pair, "volume.h24"),
        "txns_m5_buys": dig(pair, "txns.m5.buys"),
        "txns_m5_sells": dig(pair, "txns.m5.sells"),
        "txns_h1_buys": dig(pair, "txns.h1.buys"),
        "txns_h1_sells": dig(pair, "txns.h1.sells"),
        "priceChange_m5": dig(pair, "priceChange.m5"),
        "priceChange_h1": dig(pair, "priceChange.h1"),
        "priceChange_h24": dig(pair, "priceChange.h24"),
        "pairCreatedAt": pair.get("pairCreatedAt"),
        "name": dig(pair, "baseToken.name"),
        "symbol": dig(pair, "baseToken.symbol"),
        "mint": dig(pair, "baseToken.address"),
    }


def rugcheck_creator(report: Mapping[str, Any]) -> Any:
    return report.get("creator")


def rugcheck_market_for_pool(report: Mapping[str, Any], pool: str) -> Optional[dict[str, Any]]:
    """Return the markets[] entry whose pubkey equals the Scanner/DexScreener pool."""
    for m in report.get("markets") or []:
        if isinstance(m, dict) and m.get("pubkey") == pool:
            return m
    return None


def rugcheck_lp_locked_pct(market: Optional[Mapping[str, Any]]) -> Any:
    """Locked percent, or None if the market or key is missing (never a guessed pass)."""
    if not market:
        return None
    lp = market.get("lp")
    if not isinstance(lp, dict) or "lpLockedPct" not in lp:
        return None
    return lp.get("lpLockedPct")


def graph_networks(graph_body: Any) -> list[dict[str, Any]]:
    return [n for n in graph_body if isinstance(n, dict)] if isinstance(graph_body, list) else []


def graph_has_edges_key(graph_body: Any) -> bool:
    """The sample has links, not edges. Auditor must not invent an edges key."""
    for net in graph_networks(graph_body):
        if "edges" in net:
            return True
    return False


def mint_authorities(rpc_get_account_info: Mapping[str, Any]) -> dict[str, Any]:
    info = dig(rpc_get_account_info, "result.value.data.parsed.info") or {}
    return {
        "mintAuthority": info.get("mintAuthority") if isinstance(info, dict) else None,
        "freezeAuthority": info.get("freezeAuthority") if isinstance(info, dict) else None,
        "supply": info.get("supply") if isinstance(info, dict) else None,
        "decimals": info.get("decimals") if isinstance(info, dict) else None,
        "program": dig(rpc_get_account_info, "result.value.data.program"),
        "owner": dig(rpc_get_account_info, "result.value.owner"),
    }


def token_account_delegate(gpa_item: Mapping[str, Any]) -> Any:
    """Delegate pubkey, or None if the key is omitted / unset."""
    return dig(gpa_item, "account.data.parsed.info.delegate")


__all__ = [
    "TOKEN_PROGRAM",
    "TOKEN_2022_PROGRAM",
    "MIGRATION_FIELDS",
    "DEX_FIELDS",
    "RUGCHECK_REPORT_FIELDS",
    "RUGCHECK_GRAPH_FIELDS",
    "RPC_MINT_FIELDS",
    "RPC_TOKEN_ACCOUNT_FIELDS",
    "dig",
    "migration_fields",
    "pumpswap_pair",
    "dex_fields",
    "rugcheck_creator",
    "rugcheck_market_for_pool",
    "rugcheck_lp_locked_pct",
    "graph_networks",
    "graph_has_edges_key",
    "mint_authorities",
    "token_account_delegate",
]


if __name__ == "__main__":
    import json
    from pathlib import Path

    raw = Path(__file__).resolve().parent / "logs" / "raw"
    mig = json.loads((raw / "pumpportal_migration.json").read_text())
    dex = json.loads((raw / "dexscreener_pair.json").read_text())
    report = json.loads((raw / "rugcheck_report.json").read_text())
    graph = json.loads((raw / "rugcheck_insiders_graph.json").read_text())
    acct = json.loads((raw / "rpc_getaccountinfo_mint.json").read_text())

    mf = migration_fields(mig)
    df = dex_fields(dex)
    assert mf["mint"] and mf["signature"]
    assert mf["pool"] == "pump-amm" and mf["pool_is_address"] is False
    assert mf["creator"] is None
    assert df and df["dexId"] == "pumpswap" and df["pairAddress"]
    market = rugcheck_market_for_pool(report, df["pairAddress"])
    assert market is not None
    locked = rugcheck_lp_locked_pct(market)
    assert locked is not None
    assert graph_has_edges_key(graph) is False
    assert graph_networks(graph) and "links" in graph_networks(graph)[0]
    auth = mint_authorities(acct)
    assert "mintAuthority" in auth and "freezeAuthority" in auth and auth["decimals"] == 6
    print("fields.py self-check ok")
    print("migration", {k: mf[k] for k in ("mint", "pool", "creator", "pool_is_address")})
    print("dex pair", df["pairAddress"], "liq", df["liquidity_usd"])
    print("rug creator", rugcheck_creator(report), "lpLockedPct", locked)
    print("graph networks", len(graph_networks(graph)), "edges_key", graph_has_edges_key(graph))
    print("mint auth", auth)
