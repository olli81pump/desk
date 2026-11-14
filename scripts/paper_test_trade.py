#!/usr/bin/env python3
"""ONE PAPER test trade on a live graduated PumpSwap coin. Never places an order."""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from db import DB, current_night
from links import coin_url
from rpcutil import Rpc
from sources import HttpSources, rugcheck_creator
from notify import Telegram, paper, buy_keyboard
from publisher import publish, write_state
from snapshot import build as build_snapshot
from agents import auditor as auditor_mod
from agents import analyst as analyst_mod
from agents import brain as brain_mod
from agents import executor as executor_mod
import settings as S

# Foodcoin — live PumpSwap pair, ~$90k liquidity, currently trading.
MINT = "FTu55MyigXns96jz4nTCDDiTCjYJjyrHSceCgG9Upump"
POOL = "2XhQqp1vDVxtaa21bPsekQF5gjts9euqRPSZ6Urs41qk"


async def fetch_ohlcv(pool: str) -> list[tuple[str, float]]:
    url = (
        "https://api.geckoterminal.com/api/v2/networks/solana/pools/"
        f"{pool}/ohlcv/minute?aggregate=5&limit=48"
    )
    out: list[tuple[str, float]] = []
    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as sess:
            async with sess.get(url, headers={"User-Agent": "grok-bot-desk/1.0", "Accept": "application/json"}) as r:
                if r.status >= 400:
                    return out
                body = await r.json()
        # data.attributes.ohlcv_list: [ts, o, h, l, c, vol]
        rows = ((body.get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
        for row in rows:
            if not row or len(row) < 5:
                continue
            ts = int(row[0])
            close = float(row[4])
            iso = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
            out.append((iso, close))
    except Exception as e:
        print("ohlcv skip:", type(e).__name__)
    return out


async def main() -> int:
    db = await DB().open()
    await db.c.execute("PRAGMA busy_timeout=15000")
    await db.c.commit()
    s = await db.load_settings()
    if (s.get("mode") or "PAPER") != "PAPER":
        print("refusing: desk is not in PAPER mode")
        await db.close()
        return 2
    night = current_night(s.get("report_time") or "08:00")
    http = HttpSources()
    rpc = Rpc(s.get("rpc_url") or "https://api.mainnet-beta.solana.com")
    try:
        dexmap = await http.dexscreener([MINT])
        dex = dexmap.get(MINT)
        if not dex or dex.get("priceUsd") is None:
            print("no live DexScreener price")
            return 3
        if (dex.get("dexId") or "").lower() != "pumpswap":
            print("not a PumpSwap pair:", dex.get("dexId"))
            return 3
        price = float(dex["priceUsd"])
        liq = float(dex.get("liquidity_usd") or 0)
        name = dex.get("name") or "Foodcoin"
        symbol = dex.get("symbol") or "FOOD"
        pool = dex.get("pairAddress") or POOL
        print(f"picked {name} ({symbol}) price={price} liq={liq:.2f} dex={dex.get('dexId')} pool={pool}")

        link = coin_url(MINT, "solana")
        now = datetime.now(timezone.utc)
        await db.upsert_coin(
            mint=MINT, name=name, symbol=symbol, pool=pool,
            seen_at=now.isoformat(), night=night, status="test", coin_url=link,
        )
        # creator from rugcheck if present
        try:
            report = await http.rug_report(MINT)
            if report and rugcheck_creator(report):
                await db.upsert_coin(mint=MINT, creator=rugcheck_creator(report))
        except Exception as e:
            print("rugcheck creator skip:", type(e).__name__, e)

        coin = dict(await db.coin(MINT))

        print("running auditor...")
        audit = await auditor_mod.run_audit(
            MINT, coin, s, rpc, http, scanner_liq=liq,
        )
        audit["name"] = name
        await db.add_audit(audit)
        layers = audit.get("layers") or []
        print("auditor passed=", audit.get("passed"), "reason=", audit.get("reason"), "layersChecked=", audit.get("layersChecked"))
        for L in layers:
            print(f"  L{L.get('n')} {L.get('name')} pass={L.get('pass')} value={L.get('value')}")

        # Analyst — real score, even if it would reject
        layer_vals = {L["n"]: L.get("value") for L in layers}
        audit_facts = {
            "bundled_n": audit.get("bundled_n"),
            "bundled": audit.get("bundled_n"),
            "top10": layer_vals.get(4),
            "dev": layer_vals.get(3),
            "lp": layer_vals.get(5),
            "delegations": layer_vals.get(8),
        }
        analysis = analyst_mod.analyse(dex, audit_facts, s, MINT, name)
        await db.add_analysis(analysis)
        score = float(analysis.get("score") or 0)
        failed = analysis.get("failed") or []
        print("analyst score=", score, "passed=", analysis.get("passed"), "failed=", failed)

        stack = float(s.get("paper_balance") or 50)
        openp = await db.open_positions()
        in_use = sum(float(p["size_usd"] or 0) for p in openp)
        free = stack - in_use
        sized = brain_mod.size_buy(score, liq, stack, free, s, mint=MINT)
        # Force a test fill: if score < 70 Brain already floors at $5; if a cap skipped, use $5 when free allows.
        if sized.get("skipped") or float(sized.get("sizeUsd") or 0) <= 0:
            floor = float(s.get("min_size_usd") or 5)
            sized = {
                "agent": "brain",
                "mint": MINT,
                "score": score,
                "sizeUsd": floor if free >= floor else max(0.0, free),
                "stackPct": (floor / stack * 100.0) if stack else 0,
                "capHit": sized.get("capHit"),
                "reason": "TEST forced min size",
                "skipped": False,
                "raw": sized.get("raw") or floor,
            }
        sized["night"] = night
        sized["ts"] = now.isoformat()
        await db.add_brain(sized)
        size = float(sized["sizeUsd"])
        stack_pct = float(sized.get("stackPct") or (size / stack * 100.0 if stack else 0))
        print("brain sizeUsd=", size, "stackPct=", stack_pct, "capHit=", sized.get("capHit"), "score=", score)

        # Activity — clearly labeled TEST
        aud_ok = bool(audit.get("passed"))
        await db.add_activity(
            kind="audited" if aud_ok else "rejected",
            mint=MINT,
            title=f"TEST · {name}" if aud_ok else f"TEST · Auditor {name}",
            agent="Auditor",
            detail="TEST · 8/8 → Analyst" if aud_ok else f"TEST · {audit.get('reason')}",
            right="8/8 → Analyst" if aud_ok else "Forced through",
            link=link,
            tone="pass" if aud_ok else "reject",
            night=night,
        )
        an_ok = bool(analysis.get("passed"))
        fail_txt = (failed[0] if failed else "gate")
        await db.add_activity(
            kind="scored" if an_ok else "rejected",
            mint=MINT,
            title=f"TEST · {name}" if an_ok else f"TEST · Analyst {name}",
            agent="Analyst (rules)",
            detail=f"TEST · score {score:.0f}" if an_ok else f"TEST · {fail_txt}",
            right=f"{score:.0f}" if an_ok else "Forced through",
            link=link,
            tone="pass" if an_ok else "reject",
            night=night,
        )
        await db.add_activity(
            kind="sized",
            mint=MINT,
            title=f"TEST · Sized {name}",
            agent="Brain",
            detail=f"TEST · score {score:.0f}",
            right=f"${size:.2f} · {stack_pct:.2f}% of stack",
            link=link,
            tone="pass",
            night=night,
        )

        # Executor PAPER fill at the live polled price — no order is placed
        payload = executor_mod.execution_payload(MINT, price, size, stack, link, "PAPER", "bought")
        payload["reason"] = "TEST"
        await db.add_execution(payload)
        await db.c.execute(
            "INSERT INTO positions(mint,name,symbol,status,mode,opened_at,entry_price,peak_price,"
            "size_usd,stop_pct,trail_active,link,night,original_size_usd,realized_pnl_usd,"
            "tp1_hit,tp2_hit,fees_realized_usd) VALUES(?,?,?,?,?,?,?,?,?,?,0,?,?,?,0,0,0,0)",
            (
                MINT, name, symbol, "open", "PAPER",
                now.isoformat(), price, price,
                size, float(s["stop_pct"]), link, night, size,
            ),
        )
        await db.c.commit()
        await db.add_activity(
            kind="bought",
            mint=MINT,
            title=f"TEST · Bought {name}",
            agent="Executor",
            detail=f"TEST · {now.strftime('%H:%M')}",
            right=f"${size:.2f} · {stack_pct:.2f}% of stack",
            link=link,
            tone="buy",
            night=night,
        )
        await db.upsert_coin(mint=MINT, status="open")

        # Chart history so Home / Coin can mark entry, stop, TP lines
        candles = await fetch_ohlcv(pool)
        if candles:
            for ts, px in candles:
                await db.add_price(MINT, px, None, ts)
        else:
            # fall back to a short synthetic path from h1 change so the chart has marks
            h1 = float(dex.get("priceChange_h1") or 0)
            prev = price / (1.0 + h1 / 100.0) if h1 > -99 else price * 0.99
            await db.add_price(MINT, prev, dex.get("volume_m5"), (now - timedelta(hours=1)).isoformat())
        await db.add_price(MINT, price, dex.get("volume_m5"), now.isoformat())

        # Telegram buy push — the only test push for this trade
        text = paper(f"TEST · {name} · ${size:.2f} · {stack_pct:.2f}% of stack")
        tg = Telegram()
        sent = await tg.send(text, buy_keyboard(MINT))
        await tg.close()
        print("telegram_sent", sent, "text", text)
        print("coin_url", link)

        # Publish so the app shows it
        state = await build_snapshot(db, s, extra={"night": night, "ticket": S.ticket_check(s)})
        write_state(state)
        ok = publish()
        print("published", ok)

        # Confirm visibility without printing the data path
        poss = [p for p in (state.get("positions") or []) if p.get("mint") == MINT]
        acts = [a for a in (state.get("activity") or []) if a.get("mint") == MINT]
        coin = (state.get("coins") or {}).get(MINT) or {}
        print("visible_position", bool(poss), "activity_rows", len(acts), "coin_in_state", bool(coin), "prices", len(coin.get("prices") or []))
        if poss:
            print("entry", poss[0].get("entry_price"), "size", poss[0].get("size_usd"), "mode", poss[0].get("mode"))

        print("REPORT")
        print("name", name)
        print("symbol", symbol)
        print("mint", MINT)
        print("coin_url", link)
        print("entry_price", price)
        print("size_usd", size)
        print("stack_pct", stack_pct)
        print("auditor_passed", audit.get("passed"))
        print("auditor_reason", audit.get("reason"))
        print("auditor_layers", json.dumps(layers, default=str))
        print("analyst_score", score)
        print("analyst_passed", analysis.get("passed"))
        print("analyst_failed", failed)
        print("forced", (not aud_ok) or (not an_ok))
        return 0 if sent else 1
    finally:
        await rpc.close()
        await http.close()
        await db.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
