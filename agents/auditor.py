"""Auditor: 8 layers in order. One red and the coin is dead. No 'mostly clean'."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Awaitable

from rpcutil import mint_authorities_from_account, parsed_token_info, bonding_curve_pda
from sources import (
    rugcheck_creator,
    rugcheck_market_for_pool,
    rugcheck_lp_locked_pct,
    graph_networks,
)

log = logging.getLogger("auditor")

LAYER_NAMES = {
    1: "Mint authority",
    2: "Freeze authority",
    3: "Dev wallet",
    4: "Top 10 holders",
    5: "Liquidity",
    6: "Pool age",
    7: "Bundled wallets",
    8: "Delegations",
}


def _layer(n: int, ok: bool, value: str, source: str) -> dict:
    return {"n": n, "name": LAYER_NAMES[n], "pass": ok, "value": value, "source": source}


def unpaid(from_n: int) -> list[dict]:
    return [
        {"n": i, "name": LAYER_NAMES[i], "pass": None, "value": "not checked", "source": None}
        for i in range(from_n, 9)
    ]


def connected_components(nodes: list[str], links: list[tuple[str, str]], holders: set[str]) -> list[set[str]]:
    """Bundled = size of the biggest group of holders joined by links/edges."""
    hold = {n for n in nodes if n in holders} if holders else set(nodes)
    adj: dict[str, set[str]] = {n: set() for n in hold}
    for a, b in links:
        if a in hold and b in hold:
            adj.setdefault(a, set()).add(b)
            adj.setdefault(b, set()).add(a)
    seen: set[str] = set()
    groups = []
    for n in adj:
        if n in seen:
            continue
        stack = [n]
        g = set()
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x)
            g.add(x)
            stack.extend(adj.get(x, ()))
        if g:
            groups.append(g)
    return groups


def bundled_from_graph(graph, holders: set[str]) -> tuple[int | None, str | None]:
    """Return (biggest_group, error). Uses 'links' as edges; if neither links nor edges -> error."""
    nets = graph_networks(graph)
    if not nets:
        # empty list is still a graph with no edges/links keys
        return None, "no data: bundles"
    any_edge_key = False
    all_links: list[tuple[str, str]] = []
    all_nodes: list[str] = []
    for net in nets:
        if "edges" in net or "links" in net:
            any_edge_key = True
        raw = net.get("links") or net.get("edges") or []
        for e in raw:
            if isinstance(e, dict):
                a, b = e.get("source"), e.get("target")
                if a and b:
                    all_links.append((str(a), str(b)))
        for n in net.get("nodes") or []:
            if isinstance(n, dict) and n.get("id"):
                all_nodes.append(str(n["id"]))
            elif isinstance(n, str):
                all_nodes.append(n)
    if not any_edge_key:
        return None, "no data: bundles"
    if holders:
        # keep only wallets that hold this mint
        node_set = set(all_nodes) | {a for a, b in all_links} | {b for a, b in all_links}
        use = node_set & holders
    else:
        use = set(all_nodes) | {a for a, b in all_links} | {b for a, b in all_links}
    groups = connected_components(list(use), all_links, use)
    biggest = max((len(g) for g in groups), default=0)
    return biggest, None


def format_lp(pct: float | None) -> str:
    if pct is None:
        return "no data: liquidity"
    return f"{pct:.2f}% locked"


def _ui_amount(raw) -> float:
    if isinstance(raw, dict):
        raw = raw.get("uiAmount") or raw.get("uiAmountString") or raw.get("amount")
    try:
        return float(raw or 0)
    except (TypeError, ValueError):
        return 0.0


def top10_from_accounts(accs: list, mint: str, pool: str | None, supply_ui: float | None) -> float | None:
    """Sum the 10 largest token-account balances, excluding the pool and bonding curve."""
    if not supply_ui or not accs:
        return None
    curve = bonding_curve_pda(mint)
    exclude = {x for x in (pool, curve) if x}
    bals: list[float] = []
    for item in accs:
        info = parsed_token_info(item) if isinstance(item, dict) and (item.get("account") or item.get("pubkey")) else {}
        if not info and isinstance(item, dict):
            # already-flattened {pubkey, owner, uiAmount} rows from tests
            info = item
        pubkey = item.get("pubkey") or item.get("address") if isinstance(item, dict) else None
        owner = info.get("owner")
        if (owner and owner in exclude) or (pubkey and pubkey in exclude):
            continue
        ui = _ui_amount(info.get("tokenAmount") if "tokenAmount" in info else info.get("uiAmount") or info.get("uiAmountString"))
        if ui <= 0:
            continue
        bals.append(ui)
    if not bals:
        return None
    bals.sort(reverse=True)
    return (sum(bals[:10]) / float(supply_ui)) * 100.0


async def top10_from_largest(rpc, mint: str, pool: str | None, supply_ui: float | None) -> float | None:
    if not supply_ui:
        return None
    largest = await rpc.get_token_largest(mint)
    if not largest:
        return None
    curve = bonding_curve_pda(mint)
    exclude = {x for x in (pool, curve) if x}
    total = 0.0
    counted = 0
    for acc in largest:
        addr = acc.get("address")
        ui = _ui_amount(acc.get("uiAmount") or acc.get("uiAmountString") or acc)
        owner = None
        if addr:
            try:
                info = await rpc.get_account_info(addr, retries=1)
                parsed = (((info or {}).get("data") or {}).get("parsed") or {}).get("info") or {}
                owner = parsed.get("owner")
            except Exception:
                owner = None
        if (owner and owner in exclude) or (addr and addr in exclude):
            continue
        if ui <= 0:
            continue
        total += ui
        counted += 1
        if counted >= 10:
            break
    if counted == 0:
        return None
    return (total / float(supply_ui)) * 100.0


async def top10_with_source(
    rpc,
    mint: str,
    pool: str | None,
    supply_ui: float | None,
    accounts: list | None = None,
    retries: int = 3,
) -> tuple[float | None, str | None]:
    """Try getTokenLargestAccounts (with retries), then getProgramAccounts.

    Returns (percent, source). source is 'getTokenLargestAccounts',
    'getProgramAccounts', or None if both failed.
    """
    last_err = None
    for i in range(max(1, int(retries or 1))):
        try:
            t10 = await top10_from_largest(rpc, mint, pool, supply_ui)
            if t10 is not None:
                log.info("layer 4 top10=%.2f%% source=getTokenLargestAccounts mint=%s", t10, mint)
                return t10, "getTokenLargestAccounts"
            last_err = "empty"
        except Exception as e:
            last_err = e
            log.warning("getTokenLargestAccounts try %s/%s failed: %s", i + 1, retries, e)
        if i + 1 < retries:
            import asyncio
            await asyncio.sleep(2)
    # Fallback: same GPA used for layer 8
    accs = accounts
    if accs is None:
        try:
            accs = await rpc.get_program_accounts_for_mint(mint)
        except Exception as e:
            log.warning("getProgramAccounts for top10 failed: %s", e)
            accs = None
    t10 = top10_from_accounts(accs or [], mint, pool, supply_ui)
    if t10 is not None:
        log.info("layer 4 top10=%.2f%% source=getProgramAccounts mint=%s", t10, mint)
        return t10, "getProgramAccounts"
    log.warning("layer 4 no data: top 10 (largest=%s, gpa=%s) mint=%s", last_err, "empty" if not accs else "unusable", mint)
    return None, None


async def top10_pct(
    rpc,
    mint: str,
    pool: str | None,
    supply_ui: float | None,
    accounts: list | None = None,
    retries: int = 3,
) -> float | None:
    """Scanner/legacy helper. Percent of supply held by the top 10, or None."""
    t10, _src = await top10_with_source(rpc, mint, pool, supply_ui, accounts=accounts, retries=retries)
    return t10


async def run_audit(
    mint: str,
    coin: dict,
    s: dict,
    rpc,
    sources,
    on_layer: Callable[[dict], Awaitable[None]] | None = None,
    scanner_liq: float | None = None,
) -> dict:
    layers: list[dict] = []
    ts = datetime.now(timezone.utc).isoformat()
    holders_n = None
    bundled_n = None
    reason = None
    passed = False
    checked = 0

    async def emit(L: dict) -> None:
        layers.append(L)
        if on_layer:
            await on_layer(L)

    def fail(n: int, value: str, source: str) -> dict:
        return _finish(False, n, value, value)

    def _finish(ok: bool, n: int, value: str | None, first_red: str | None) -> dict:
        nonlocal passed, reason, checked
        passed = ok
        checked = n
        reason = None if ok else (first_red or value)
        return {
            "agent": "auditor",
            "mint": mint,
            "ts": ts,
            "passed": ok,
            "layersChecked": n,
            "layers": layers + (unpaid(n + 1) if not ok and n < 8 else []),
            "holders": holders_n,
            "reason": reason,
            "bundled_n": bundled_n,
        }

    retries = int(s.get("auditor_retries") or 3)

    # Layer 1-2: mint + freeze from one getAccountInfo
    try:
        acc = await rpc.get_account_info(mint, retries=retries)
        auth = mint_authorities_from_account(acc)
        if not auth.get("ok"):
            await emit(_layer(1, False, "no data: mint", "rpc"))
            return fail(1, "no data: mint", "rpc")
    except Exception:
        await emit(_layer(1, False, "no data: mint", "rpc"))
        return fail(1, "no data: mint", "rpc")

    ok1 = auth["mintAuthority"] in (None, "")
    await emit(_layer(1, ok1, "Revoked" if ok1 else "mint not revoked", "rpc"))
    if not ok1:
        return fail(1, "mint not revoked", "rpc")

    ok2 = auth["freezeAuthority"] in (None, "")
    await emit(_layer(2, ok2, "Revoked" if ok2 else "freeze not revoked", "rpc"))
    if not ok2:
        return fail(2, "freeze not revoked", "rpc")

    # Layer 3: dev wallet — creator from coin (RugCheck if migration had none)
    creator = coin.get("creator")
    try:
        supply_ui, _ = await rpc.get_token_supply(mint)
    except Exception:
        supply_ui = None
    if supply_ui is None or supply_ui == 0:
        # try parsed supply
        try:
            supply_ui = float(auth["supply"]) / (10 ** int(auth["decimals"] or 0)) if auth.get("supply") else None
        except Exception:
            supply_ui = None
    if not supply_ui:
        await emit(_layer(3, False, "no supply", "rpc"))
        return fail(3, "no supply", "rpc")
    if not creator:
        await emit(_layer(3, False, "no data: dev", "rpc"))
        return fail(3, "no data: dev", "rpc")
    try:
        dev_bal = await rpc.owner_balance_ui(creator, mint)
    except Exception:
        await emit(_layer(3, False, "no data: dev", "rpc"))
        return fail(3, "no data: dev", "rpc")
    dev_pct = (dev_bal / supply_ui) * 100.0
    at_mig = coin.get("creator_balance_at_migration")
    sold = at_mig is not None and dev_bal < float(at_mig) - 1e-9
    if dev_pct >= float(s["max_dev_pct"]):
        await emit(_layer(3, False, f"dev holds {dev_pct:.1f}%", "rpc"))
        return fail(3, f"dev holds {dev_pct:.1f}%", "rpc")
    if sold:
        await emit(_layer(3, False, "dev sold", "rpc"))
        return fail(3, "dev sold", "rpc")
    sold_txt = "sold 0" if (at_mig is None or abs(dev_bal - float(at_mig)) < 1e-6) else "held"
    await emit(_layer(3, True, f"{dev_pct:.1f}% · {sold_txt}", "rpc"))

    # Fetch Token + Token-2022 accounts once; reuse for layer 4 fallback and layer 8
    gpa_accs = None
    try:
        gpa_accs = await rpc.get_program_accounts_for_mint(mint)
    except Exception as e:
        log.warning("getProgramAccounts (shared 4/8) failed: %s", e)
        gpa_accs = None

    # Layer 4: top 10
    try:
        t10, t10_src = await top10_with_source(
            rpc, mint, coin.get("pool"), supply_ui, accounts=gpa_accs, retries=retries,
        )
    except Exception:
        t10, t10_src = None, None
    if t10 is None:
        await emit(_layer(4, False, "no data: top 10", t10_src or "rpc"))
        return fail(4, "no data: top 10", t10_src or "rpc")
    cap = float(s.get("auditor_max_top10_pct") or s.get("max_top10_pct") or 25)
    src4 = t10_src or "rpc"
    if t10 >= cap:
        await emit(_layer(4, False, f"top 10 hold {t10:.1f}%", src4))
        return fail(4, f"top 10 hold {t10:.1f}%", src4)
    await emit(_layer(4, True, f"{t10:.1f}%", src4))

    # Layer 5: LP locked via RugCheck market pubkey == pair/pool
    report = None
    try:
        report = await sources.rug_report(mint)
    except Exception:
        report = None
    pool = coin.get("pool")
    market = rugcheck_market_for_pool(report or {}, pool) if report and pool else None
    locked = rugcheck_lp_locked_pct(market) if market else None
    if locked is None:
        await emit(_layer(5, False, "no data: liquidity", "rugcheck"))
        return fail(5, "no data: liquidity", "rugcheck")
    if float(locked) < float(s["min_lp_locked_pct"]):
        await emit(_layer(5, False, "liquidity unlocked", "rugcheck"))
        return fail(5, "liquidity unlocked", "rugcheck")
    # liquidity not down > 50% since Scanner
    try:
        dex = await sources.dexscreener([mint])
        now_liq = (dex.get(mint) or {}).get("liquidity_usd")
    except Exception:
        now_liq = None
    if scanner_liq and now_liq is not None:
        try:
            if float(now_liq) < float(scanner_liq) * 0.5:
                await emit(_layer(5, False, "liquidity pulled", "rugcheck"))
                return fail(5, "liquidity pulled", "rugcheck")
        except (TypeError, ValueError):
            pass
    await emit(_layer(5, True, format_lp(float(locked)), "rugcheck"))

    # Layer 6: pool age
    migrated_at = coin.get("migrated_at")
    age_min = 0
    if migrated_at:
        try:
            t0 = datetime.fromisoformat(str(migrated_at).replace("Z", "+00:00"))
            age_min = int((datetime.now(timezone.utc) - t0).total_seconds() // 60)
        except Exception:
            age_min = 0
    need = int(s.get("auditor_min_pool_age_min") or s.get("min_pool_age_min") or 10)
    if age_min < need:
        await emit(_layer(6, False, "pool too young", "rpc"))
        return fail(6, "pool too young", "rpc")
    await emit(_layer(6, True, f"{age_min}m", "rpc"))

    # Layer 7: bundles via graph links
    try:
        graph = await sources.rug_graph(mint)
    except Exception:
        graph = None
    # holders set filled in layer 8; for layer 7 we use graph node holdings > 0 if present
    holder_guess: set[str] = set()
    for net in graph_networks(graph):
        for n in net.get("nodes") or []:
            if isinstance(n, dict) and n.get("id") and float(n.get("holdings") or 0) > 0:
                holder_guess.add(str(n["id"]))
    biggest, gerr = bundled_from_graph(graph, holder_guess)
    if gerr or biggest is None:
        await emit(_layer(7, False, gerr or "no data: bundles", "rugcheck"))
        return fail(7, gerr or "no data: bundles", "rugcheck")
    bundled_n = biggest
    if biggest >= int(s["max_bundled"]):
        await emit(_layer(7, False, f"{biggest} bundled wallets", "rugcheck"))
        return fail(7, f"{biggest} bundled wallets", "rugcheck")
    await emit(_layer(7, True, "None" if biggest <= 1 else str(biggest), "rugcheck"))

    # Layer 8: delegations on Token AND Token-2022 (reuse the GPA fetched above)
    accs = gpa_accs
    if accs is None:
        await emit(_layer(8, False, "no data: delegations", "rpc"))
        return fail(8, "no data: delegations", "rpc")

    holders_n = 0
    by_delegate: dict[str, int] = {}
    for item in accs:
        info = parsed_token_info(item)
        amt = (info.get("tokenAmount") or {}).get("uiAmount") or 0
        try:
            if float(amt) > 0:
                holders_n += 1
        except (TypeError, ValueError):
            pass
        delegated = info.get("delegate")
        if delegated:
            by_delegate[delegated] = by_delegate.get(delegated, 0) + 1
    cap_d = int(s["max_delegated_accounts"])
    bad = [(d, n) for d, n in by_delegate.items() if n > cap_d]
    if bad:
        d, n = max(bad, key=lambda x: x[1])
        short = d[:6] + "..." + d[-3:] if len(d) > 12 else d
        val = f"{n} wallets → {short}"
        await emit(_layer(8, False, val, "rpc"))
        return fail(8, val, "rpc")
    await emit(_layer(8, True, "None", "rpc"))
    return _finish(True, 8, None, None)
