#!/usr/bin/env python3
"""Always-on PAPER desk. Never loads private keys, never signs or sends transactions, never places orders."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from db import DB, current_night
from links import SIGNUP_URL, coin_url
from fees import round_trip_fees
import settings as S
from rpcutil import Rpc, bonding_curve_pda
from sources import HttpSources, rugcheck_creator
from pathlib import Path as _P
ROOT_DIR_CLOSE = _P(__file__).resolve().parent / "data"
from notify import Telegram, paper, buy_keyboard, sell_keyboard
from publisher import publish, write_state
from snapshot import build as build_snapshot
from agents.scanner import scanner_pass
from agents import auditor as auditor_mod
from agents import analyst as analyst_mod
from agents import brain as brain_mod
from agents import executor as executor_mod
from agents import risk as risk_mod
import commands as cmds

LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
PID_FILE = LOG_DIR / "desk.pid"


def _setup_logging() -> None:
    fmt = logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root.addHandler(sh)
    fh = logging.FileHandler(LOG_DIR / "desk.log")
    fh.setFormatter(fmt)
    root.addHandler(fh)
    for agent in ("scanner", "auditor", "analyst", "brain", "executor", "risk"):
        h = logging.FileHandler(LOG_DIR / f"{agent}.log")
        h.setFormatter(fmt)
        logging.getLogger(agent).addHandler(h)


log = logging.getLogger("desk")


class Desk:
    def __init__(self):
        self.db: DB | None = None
        self.settings: dict = S.fresh()
        self.rpc: Rpc | None = None
        self.http: HttpSources | None = None
        self.tg: Telegram | None = None
        self.bus_auditor: asyncio.Queue = asyncio.Queue()
        self.bus_analyst: asyncio.Queue = asyncio.Queue()
        self.bus_brain: asyncio.Queue = asyncio.Queue()
        self.bus_executor: asyncio.Queue = asyncio.Queue()
        self.night = current_night(self.settings.get("report_time") or "08:00")
        self.ticket: dict | None = None
        self.running = True
        self.seen_mints: set[str] = set()
        self.pushed_tonight: set[str] = set()
        self.ws_reconnects_hour = 0

    async def start(self) -> None:
        self.db = await DB().open()
        self.settings = await self.db.load_settings()
        # force confirmed defaults that must not be overwritten wrongly
        self.settings["fomo_handle"] = "olli81"
        self.settings["analyst_mode"] = "rules"
        self.settings["notifier"] = "telegram"
        self.settings["rpc_url"] = self.settings.get("rpc_url") or "https://api.mainnet-beta.solana.com"
        if self.settings.get("mode") != "LIVE":
            self.settings["mode"] = "PAPER"
        if self.settings.get("paper_balance") is None:
            self.settings["paper_balance"] = self.settings["paper_start_stack"]
        import notify as _notify
        _notify.MODE = self.settings["mode"]
        await self.db.save_settings(self.settings)
        self.night = current_night(self.settings.get("report_time") or "08:00")
        await self.db.execute(
            "INSERT OR IGNORE INTO night_meta(night, started_at, paper_complete) VALUES(?,?,0)",
            (self.night, datetime.now(timezone.utc).isoformat()),
        )
        self.rpc = Rpc(self.settings["rpc_url"])
        self.http = HttpSources()
        self.tg = Telegram()
        self.ticket = S.ticket_check(self.settings)
        if self.ticket.get("warning"):
            await self.announce(self.ticket["warning"])
        # already-seen tonight
        rows = await self.db.fetchall("SELECT mint FROM coins WHERE night=?", (self.night,))
        self.seen_mints = {r["mint"] for r in rows}
        rows = await self.db.fetchall(
            "SELECT mint FROM executions WHERE status IN ('sent','bought')"
        )
        self.pushed_tonight = {r["mint"] for r in rows}
        await self.publish_now()

    async def close(self) -> None:
        self.running = False
        if self.rpc:
            await self.rpc.close()
        if self.http:
            await self.http.close()
        if self.tg:
            await self.tg.close()
        if self.db:
            await self.db.close()

    @property
    def paused(self):
        async def _p():
            return await self.db.get_kv("paused", {}) or {}
        return _p()

    async def is_paused(self, agent: str) -> bool:
        p = await self.db.get_kv("paused", {}) or {}
        return bool(p.get(agent))

    async def beat(self, agent: str, **extra) -> None:
        await self.db.heartbeat(agent, extra or None)

    async def announce(self, text: str) -> None:
        if self.tg:
            await self.tg.send(text)

    async def ticket_announce(self) -> None:
        self.ticket = S.ticket_check(self.settings)
        if self.ticket.get("warning"):
            await self.announce(self.ticket["warning"])

    async def publish_now(self) -> None:
        try:
            state = await build_snapshot(self.db, self.settings, {"night": self.night, "ticket": self.ticket})
            write_state(state)
        except Exception:
            log.exception("snapshot failed")

    # ----- scanner -----
    async def scanner_ws(self) -> None:
        import websockets
        url = "wss://pumpportal.fun/api/data"
        backoff = 1
        while self.running:
            try:
                async with websockets.connect(url, open_timeout=20, ping_interval=20, ping_timeout=20) as ws:
                    await ws.send(json.dumps({"method": "subscribeMigration"}))
                    log.info("scanner subscribed")
                    backoff = 1
                    last = asyncio.get_event_loop().time()
                    while self.running:
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=30)
                        except asyncio.TimeoutError:
                            if asyncio.get_event_loop().time() - last > 120:
                                log.warning("scanner silent 120s, reconnect")
                                await self.db.log_ws_reconnect()
                                break
                            continue
                        last = asyncio.get_event_loop().time()
                        try:
                            msg = json.loads(raw)
                        except Exception:
                            continue
                        if not isinstance(msg, dict) or "mint" not in msg:
                            continue
                        await self.on_migration(msg)
            except Exception as e:
                log.warning("scanner ws: %s", e)
                await self.db.log_ws_reconnect()
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def on_migration(self, msg: dict) -> None:
        mint = msg.get("mint")
        if not mint or mint in self.seen_mints:
            return
        if await self.is_paused("scanner"):
            return
        self.seen_mints.add(mint)
        now = datetime.now(timezone.utc).isoformat()
        # pool in the message is a kind tag, not an address
        pool_field = msg.get("pool")
        pool_addr = pool_field if isinstance(pool_field, str) and 32 <= len(pool_field) <= 44 and pool_field != "pump-amm" else None
        creator = msg.get("creator") or msg.get("traderPublicKey")
        # creator usually absent — try RugCheck now so Auditor can use "sold 0"
        creator_bal = None
        if not creator:
            report = await self.http.rug_report(mint)
            if report:
                creator = rugcheck_creator(report)
        if creator:
            try:
                creator_bal = await self.rpc.owner_balance_ui(creator, mint)
            except Exception:
                creator_bal = None
        await self.db.upsert_coin(
            mint=mint,
            pool=pool_addr,
            creator=creator,
            creator_balance_at_migration=creator_bal,
            migrated_at=now,
            seen_at=now,
            night=self.night,
            status="waiting",
            coin_url=coin_url(mint, "solana"),
        )
        await self.db.execute(
            "INSERT OR IGNORE INTO waiting(mint, added_at) VALUES(?,?)",
            (mint, now),
        )
        log.info("waiting %s", mint)

    async def scanner_poll(self) -> None:
        while self.running:
            await self.beat("scanner")
            try:
                if not await self.is_paused("scanner"):
                    await self._poll_waiting()
            except Exception:
                log.exception("scanner poll")
            await asyncio.sleep(int(self.settings.get("scanner_poll_s") or 60))

    async def _poll_waiting(self) -> None:
        rows = await self.db.fetchall("SELECT * FROM waiting")
        if not rows:
            return
        mints = [r["mint"] for r in rows]
        dexmap = await self.http.dexscreener(mints)
        # today's runners for copycat
        runners = []
        for mint, d in dexmap.items():
            try:
                if d.get("priceChange_h24") is not None and float(d.get("priceChange_h24")) >= float(self.settings["runner_h24_pct"]):
                    runners.append(d)
            except (TypeError, ValueError):
                pass
        # also coins already seen today with stored h24 — keep it simple: from this batch + activity coins
        now = datetime.now(timezone.utc)
        max_wait = int(self.settings["max_wait_min"])
        for row in rows:
            mint = row["mint"]
            coin = await self.db.coin(mint)
            coin = dict(coin) if coin else {"mint": mint}
            added = datetime.fromisoformat(row["added_at"].replace("Z", "+00:00"))
            age_min = (now - added).total_seconds() / 60.0
            dex = dexmap.get(mint)
            if dex:
                # persist name/symbol/pool from DexScreener
                await self.db.upsert_coin(
                    mint=mint,
                    name=dex.get("name"),
                    symbol=dex.get("symbol"),
                    pool=dex.get("pairAddress") or coin.get("pool"),
                    coin_url=coin_url(mint, "solana"),
                )
                coin["name"] = dex.get("name") or coin.get("name")
                coin["symbol"] = dex.get("symbol") or coin.get("symbol")
                coin["pool"] = dex.get("pairAddress") or coin.get("pool")
                try:
                    price = float(dex.get("priceUsd"))
                    await self.db.add_price(mint, price, dex.get("volume_m5"))
                except (TypeError, ValueError):
                    pass
            if age_min >= max_wait and (not dex or scanner_pass(dex, None, age_min, self.settings, runners)[0] != "pass"):
                # drop if never qualified
                if not dex or scanner_pass(dex, None, age_min, self.settings, runners)[0] != "pass":
                    await self._scan_done(mint, coin, dex or {}, None, "kill", "never qualified")
                    continue
            if not dex:
                continue  # wait until DexScreener knows it
            # top 10
            top10 = None
            try:
                supply, _ = await self.rpc.get_token_supply(mint)
                from agents.auditor import top10_pct
                top10 = await top10_pct(self.rpc, mint, coin.get("pool"), supply)
            except Exception:
                top10 = None
            verdict, reason = scanner_pass(dex, top10, age_min, self.settings, runners)
            if verdict == "wait":
                continue
            await self._scan_done(mint, coin, dex, top10, verdict, reason)

    async def _scan_done(self, mint, coin, dex, top10, verdict, reason) -> None:
        payload = {
            "agent": "scanner",
            "mint": mint,
            "name": coin.get("name") or (dex or {}).get("name"),
            "symbol": coin.get("symbol") or (dex or {}).get("symbol"),
            "pool": coin.get("pool") or (dex or {}).get("pairAddress"),
            "liquidityUsd": (dex or {}).get("liquidity_usd"),
            "top10Pct": top10,
            "h1ChangePct": (dex or {}).get("priceChange_h1"),
            "ageMin": None,
            "verdict": verdict,
            "reason": reason,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        # age
        if coin.get("migrated_at"):
            try:
                t0 = datetime.fromisoformat(str(coin["migrated_at"]).replace("Z", "+00:00"))
                payload["ageMin"] = int((datetime.now(timezone.utc) - t0).total_seconds() // 60)
            except Exception:
                pass
        await self.db.add_scan(payload)
        await self.db.execute("DELETE FROM waiting WHERE mint=?", (mint,))
        name = payload["name"] or mint
        link = coin_url(mint, "solana")
        if verdict == "pass":
            await self.db.upsert_coin(mint=mint, status="auditor", name=payload["name"], symbol=payload["symbol"], pool=payload["pool"])
            await self.db.add_activity(
                kind="passed", mint=mint, title=name, agent="Scanner",
                detail=f"liq ${(dex or {}).get('liquidity_usd')} · → auditor",
                right="→ auditor", link=link, tone="pass", night=self.night,
            )
            await self.bus_auditor.put(payload)
        else:
            await self.db.upsert_coin(mint=mint, status="killed")
            await self.db.add_activity(
                kind="kill", mint=mint, title=name, agent="Scanner",
                detail=reason, right=reason, link=link, tone="kill", night=self.night,
            )
        logging.getLogger("scanner").info("%s %s %s", mint, verdict, reason)

    # ----- auditor / analyst / executor -----
    async def auditor_loop(self) -> None:
        while self.running:
            await self.beat("auditor")
            try:
                item = await asyncio.wait_for(self.bus_auditor.get(), timeout=5)
            except asyncio.TimeoutError:
                continue
            if await self.is_paused("auditor"):
                await self.bus_auditor.put(item)
                await asyncio.sleep(1)
                continue
            try:
                await self._audit_item(item)
            except Exception:
                log.exception("auditor item")

    async def audit_now(self, mint: str) -> dict:
        coin = await self.db.coin(mint)
        coin = dict(coin) if coin else {"mint": mint}
        # enrich from dex / rug if needed
        dexmap = await self.http.dexscreener([mint])
        dex = dexmap.get(mint) or {}
        if dex.get("pairAddress"):
            await self.db.upsert_coin(mint=mint, name=dex.get("name"), symbol=dex.get("symbol"), pool=dex.get("pairAddress"))
            coin = dict(await self.db.coin(mint))
        if not coin.get("creator"):
            report = await self.http.rug_report(mint)
            if report and rugcheck_creator(report):
                await self.db.upsert_coin(mint=mint, creator=rugcheck_creator(report))
                coin = dict(await self.db.coin(mint))
        result = await auditor_mod.run_audit(
            mint, coin, self.settings, self.rpc, self.http,
            scanner_liq=dex.get("liquidity_usd"),
        )
        result["name"] = coin.get("name") or dex.get("name")
        await self.db.add_audit(result)
        return result

    async def _audit_item(self, scan: dict) -> None:
        mint = scan["mint"]
        # never re-audit a rejected mint the same night
        prev = await self.db.fetchone(
            "SELECT passed FROM audits WHERE mint=? ORDER BY id DESC LIMIT 1", (mint,)
        )
        if prev and not prev["passed"]:
            return
        result = await self.audit_now(mint)
        name = result.get("name") or scan.get("name") or mint
        link = coin_url(mint, "solana")
        if result.get("passed"):
            await self.db.upsert_coin(mint=mint, status="analyst")
            await self.db.add_activity(
                kind="audited", mint=mint, title=name, agent="Auditor",
                detail="8/8 → Analyst", right="8/8 → Analyst", link=link, tone="pass", night=self.night,
            )
            await self.bus_analyst.put({"scan": scan, "audit": result})
        else:
            await self.db.upsert_coin(mint=mint, status="rejected")
            if self.settings.get("push_rejects"):
                await self.announce(paper(f"Rejected {name} / Auditor · {result.get('reason')}"))
            await self.db.add_activity(
                kind="rejected", mint=mint, title=f"Rejected {name}", agent="Auditor",
                detail=f"Auditor · {result.get('reason')}", right="Skipped",
                link=link, tone="reject", night=self.night,
            )
        logging.getLogger("auditor").info("%s passed=%s %s", mint, result.get("passed"), result.get("reason"))

    async def analyst_loop(self) -> None:
        while self.running:
            await self.beat("analyst")
            try:
                item = await asyncio.wait_for(self.bus_analyst.get(), timeout=5)
            except asyncio.TimeoutError:
                continue
            if await self.is_paused("analyst"):
                await self.bus_analyst.put(item)
                await asyncio.sleep(1)
                continue
            try:
                await self._analyse_item(item)
            except Exception:
                log.exception("analyst item")

    async def _analyse_item(self, item: dict) -> None:
        scan, audit = item["scan"], item["audit"]
        mint = scan["mint"]
        dexmap = await self.http.dexscreener([mint])
        dex = dexmap.get(mint)
        if not dex:
            payload = {
                "agent": "analyst", "mint": mint, "passed": False, "failed": ["no answer"],
                "score": 0, "model": "rules", "inputTokens": 0,
                "ts": datetime.now(timezone.utc).isoformat(),
            }
            await self.db.add_analysis(payload)
            return
        # pack audit facts for state text / organic penalty
        bundled_n = audit.get("bundled_n")
        layer_vals = {L["n"]: L.get("value") for L in (audit.get("layers") or [])}
        audit_facts = {
            "bundled_n": bundled_n,
            "bundled": bundled_n,
            "top10": layer_vals.get(4),
            "dev": layer_vals.get(3),
            "lp": layer_vals.get(5),
            "delegations": layer_vals.get(8),
        }
        result = analyst_mod.analyse(dex, audit_facts, self.settings, mint, scan.get("name") or "")
        await self.db.add_analysis(result)
        name = scan.get("name") or mint
        link = coin_url(mint, "solana")
        if result["passed"]:
            await self.db.upsert_coin(mint=mint, status="brain")
            await self.bus_brain.put({"scan": scan, "audit": audit, "analysis": result, "dex": dex})
        else:
            await self.db.upsert_coin(mint=mint, status="rejected")
            failed = (result.get("failed") or ["?"])[0]
            await self.db.add_activity(
                kind="rejected", mint=mint, title=f"Rejected {name}",
                agent="Analyst (rules)", detail=f"Analyst (rules) · {failed}",
                right="Skipped", link=link, tone="reject", night=self.night,
            )
            if self.settings.get("push_rejects"):
                await self.announce(paper(f"Rejected {name} / Analyst (rules) · {failed}"))
        logging.getLogger("analyst").info("%s score=%s passed=%s %s", mint, result.get("score"), result.get("passed"), result.get("failed"))

    async def brain_loop(self) -> None:
        while self.running:
            await self.beat("brain")
            try:
                item = await asyncio.wait_for(self.bus_brain.get(), timeout=5)
            except asyncio.TimeoutError:
                continue
            if await self.is_paused("brain"):
                await self.bus_brain.put(item)
                await asyncio.sleep(1)
                continue
            try:
                await self._brain_item(item)
            except Exception:
                log.exception("brain item")

    async def _brain_item(self, item: dict) -> None:
        scan, dex0, analysis = item["scan"], item["dex"], item["analysis"]
        mint = scan["mint"]
        mode = self.settings.get("mode") or "PAPER"
        stack = float(self.settings["paper_balance"] if mode == "PAPER" else (self.settings.get("live_stack") or 0) or 0)
        openp = await self.db.open_positions()
        in_use = sum(float(p["size_usd"] or 0) for p in openp)
        free = stack - in_use
        score = analysis.get("score")
        liq = dex0.get("liquidity_usd") if dex0 else None
        sized = brain_mod.size_buy(score, liq, stack, free, self.settings, mint=mint)
        sized["night"] = self.night
        sized["ts"] = datetime.now(timezone.utc).isoformat()
        await self.db.add_brain(sized)
        name = scan.get("name") or (dex0 or {}).get("name") or mint
        link = coin_url(mint, "solana")
        logging.getLogger("brain").info(
            "%s score=%s size=%s cap=%s skipped=%s %s",
            mint, sized.get("score"), sized.get("sizeUsd"), sized.get("capHit"),
            sized.get("skipped"), sized.get("reason"),
        )
        if sized.get("skipped"):
            await self.db.upsert_coin(mint=mint, status="skipped")
            await self.db.add_skip(mint, sized.get("reason") or "brain skip", self.night)
            await self.db.add_activity(
                kind="skipped", mint=mint, title=f"Skipped {name}",
                agent="Brain", detail=sized.get("reason") or "under min size",
                right="Skipped", link=link, tone="reject", night=self.night,
            )
            return
        await self.db.upsert_coin(mint=mint, status="executor")
        cap = f" · cap {sized['capHit']}" if sized.get("capHit") else ""
        await self.db.add_activity(
            kind="sized", mint=mint, title=f"Sized {name}",
            agent="Brain",
            detail=f"score {sized['score']:.0f}{cap}",
            right=f"${sized['sizeUsd']:.2f} · {sized['stackPct']:.2f}% of stack",
            link=link, tone="pass", night=self.night,
        )
        item["brain"] = sized
        await self.bus_executor.put(item)

    async def executor_loop(self) -> None:
        while self.running:
            await self.beat("executor")
            try:
                item = await asyncio.wait_for(self.bus_executor.get(), timeout=5)
            except asyncio.TimeoutError:
                continue
            if await self.is_paused("executor"):
                await self.bus_executor.put(item)
                await asyncio.sleep(1)
                continue
            try:
                await self._execute_item(item)
            except Exception:
                log.exception("executor item")

    async def _execute_item(self, item: dict) -> None:
        scan, dex0, analysis = item["scan"], item["dex"], item["analysis"]
        mint = scan["mint"]
        if mint in self.pushed_tonight:
            return  # 1 push per coin per night
        if await self.db.position_for_mint(mint):
            return
        mode = self.settings.get("mode") or "PAPER"
        stack = float(self.settings["paper_balance"] if mode == "PAPER" else (self.settings.get("live_stack") or 0) or 0)
        openp = await self.db.open_positions()
        in_use = sum(float(p["size_usd"] or 0) for p in openp if (p["mode"] or "PAPER") == mode)
        free = stack - in_use
        # ticket skip only if the stack cannot fund Brain's minimum size
        chk = S.ticket_check(self.settings, stack)
        self.ticket = chk
        if chk.get("block"):
            payload = executor_mod.execution_payload(mint, 0, 0, stack, coin_url(mint, "solana"), mode, "skipped", chk["warning"])
            await self.db.add_execution(payload)
            await self.db.add_skip(mint, chk["warning"], self.night)
            return
        brain = item.get("brain") or {}
        size = float(brain.get("sizeUsd") or 0)
        if size <= 0:
            payload = executor_mod.execution_payload(mint, 0, 0, stack, coin_url(mint, "solana"), mode, "skipped", brain.get("reason") or "no brain size")
            await self.db.add_execution(payload)
            await self.db.add_skip(mint, brain.get("reason") or "no brain size", self.night)
            return
        # fresh dex read
        freshmap = await self.http.dexscreener([mint])
        fresh = freshmap.get(mint) or dex0
        try:
            signal_price = float(fresh.get("priceUsd"))
        except (TypeError, ValueError):
            payload = executor_mod.execution_payload(mint, 0, 0, stack, coin_url(mint, "solana"), mode, "skipped", "no price")
            await self.db.add_execution(payload)
            await self.db.add_skip(mint, "no price", self.night)
            return
        reason = executor_mod.recheck(
            float(dex0.get("priceUsd") or signal_price),
            dex0.get("liquidity_usd"),
            fresh,
            self.settings,
        )
        if reason:
            payload = executor_mod.execution_payload(mint, signal_price, 0, stack, coin_url(mint, "solana"), mode, "skipped", reason)
            await self.db.add_execution(payload)
            await self.db.add_skip(mint, reason, self.night)
            return
        # Executor no longer sizes: take Brain's ticket, re-check free stack
        if size > free + 1e-9:
            payload = executor_mod.execution_payload(mint, signal_price, 0, stack, coin_url(mint, "solana"), mode, "skipped", "not enough free stack")
            await self.db.add_execution(payload)
            await self.db.add_skip(mint, "not enough free stack", self.night)
            return
        link = coin_url(mint, "solana")
        name = scan.get("name") or fresh.get("name") or mint
        stack_pct = float(brain.get("stackPct") or ((size / stack * 100.0) if stack else 0.0))
        payload = executor_mod.execution_payload(mint, signal_price, size, stack, link, mode, "sent")
        # push
        text = paper(f"{name} · ${size:.2f} · {stack_pct:.2f}% of stack")
        sent = await self.tg.send(text, buy_keyboard(mint), retries=3) if self.tg else False
        if not sent:
            logging.getLogger("executor").warning("push failed %s", mint)
            if mode == "LIVE":
                payload["status"] = "missed"
                payload["reason"] = "push failed"
                await self.db.add_execution(payload)
                return
            # PAPER: fill anyway so the night stays honest
            payload["reason"] = "push failed"
        self.pushed_tonight.add(mint)
        if mode == "LIVE":
            await self._send_channel_buy(name, mint, size, stack_pct)
        if True:  # PAPER fills; LIVE tracks the signal as if the user tapped Buy
            # fill at signal price when the push goes out
            payload["status"] = "bought"
            await self.db.add_execution(payload)
            await self.db.c.execute(
                "INSERT INTO positions(mint,name,symbol,status,mode,opened_at,entry_price,peak_price,"
                "size_usd,stop_pct,trail_active,link,night,original_size_usd,realized_pnl_usd,"
                "tp1_hit,tp2_hit,fees_realized_usd) VALUES(?,?,?,?,?,?,?,?,?,?,0,?,?,?,0,0,0,0)",
                (
                    mint, name, scan.get("symbol") or fresh.get("symbol"), "open", mode,
                    datetime.now(timezone.utc).isoformat(), signal_price, signal_price,
                    size, float(self.settings["stop_pct"]), link, self.night, size,
                ),
            )
            await self.db.c.commit()
            await self.db.add_activity(
                kind="bought", mint=mint, title=f"Bought {name}", agent="Executor",
                detail=datetime.now(timezone.utc).strftime("%H:%M"),
                right=f"${size:.2f} · {stack_pct:.2f}% of stack",
                link=link, tone="buy", night=self.night,
            )
        logging.getLogger("executor").info("%s size=%s status=%s", mint, size, payload["status"])

    # ----- risk -----
    async def risk_loop(self) -> None:
        misses: dict[str, int] = {}
        while self.running:
            await self.beat("risk")
            try:
                if not await self.is_paused("risk"):
                    await self._risk_poll(misses)
            except Exception:
                log.exception("risk poll")
            await asyncio.sleep(int(self.settings.get("risk_poll_s") or 15))

    async def _risk_poll(self, misses: dict[str, int]) -> None:
        poss = await self.db.open_positions()
        if not poss:
            return
        mints = [p["mint"] for p in poss]
        try:
            dexmap = await self.http.dexscreener(mints)
        except Exception:
            dexmap = {}
        now = datetime.now(timezone.utc)
        for p in poss:
            mint = p["mint"]
            p = dict(p)
            # tighter stop only: settings.stop_pct applies if tighter
            new_stop = risk_mod.tighter_stop(float(p["stop_pct"]), float(self.settings["stop_pct"]))
            if new_stop != float(p["stop_pct"]):
                await self.db.execute("UPDATE positions SET stop_pct=? WHERE id=?", (new_stop, p["id"]))
                p["stop_pct"] = new_stop
            dex = dexmap.get(mint)
            price = None
            if dex and dex.get("priceUsd") is not None:
                try:
                    price = float(dex["priceUsd"])
                    await self.db.add_price(mint, price, dex.get("volume_m5"))
                except (TypeError, ValueError):
                    price = None
            if price is None:
                misses[mint] = misses.get(mint, 0) + 1
                if misses[mint] == 4:
                    name = p["name"] or mint
                    if self.tg:
                        await self.tg.send(paper(f"{name}: no price for 1 min"), sell_keyboard(mint))
                continue
            misses[mint] = 0
            # manual close requests (one mint per line in data/close_requests.txt)
            req = ROOT_DIR_CLOSE / "close_requests.txt"
            if req.exists() and mint in req.read_text().split():
                req.write_text("\n".join(m for m in req.read_text().split() if m != mint))
                await self._close_position(p, price, "manual")
                continue
            # liquidity pulled
            liq = dex.get("liquidity_usd") if dex else None
            try:
                if liq is not None and float(liq) <= 0:
                    await self._close_position(p, price, "pulled")
                    continue
            except (TypeError, ValueError):
                pass
            ev = risk_mod.evaluate(p, price, now, self.settings)
            if ev["peak"] != p.get("peak_price") or ev["trail_active"] != bool(p.get("trail_active")):
                await self.db.execute(
                    "UPDATE positions SET peak_price=?, trail_active=? WHERE id=?",
                    (ev["peak"], 1 if ev["trail_active"] else 0, p["id"]),
                )
            logging.getLogger("risk").info(
                "%s price=%s peak=%s stop=%s trail=%s action=%s partials=%s",
                mint, price, ev["peak"], ev["stop_line"], ev["trail_line"], ev["reason"], ev.get("partials"),
            )
            if ev["reason"]:
                await self._close_position(p, price, ev["reason"])
                continue
            for part in ev.get("partials") or []:
                p = await self._take_profit(p, price, part)
                if p is None or float(p.get("size_usd") or 0) <= 1e-9:
                    break

    def _frac_label(self, fraction: float) -> str:
        if abs(fraction - 1.0 / 3.0) < 0.02 or abs(fraction - 0.333) < 0.02:
            return "1/3"
        if abs(fraction - 0.5) < 0.02:
            return "1/2"
        if abs(fraction - 2.0 / 3.0) < 0.02:
            return "2/3"
        return f"{fraction * 100:.0f}%"

    async def _take_profit(self, p: dict, price: float, part: dict) -> dict | None:
        """PAPER fill a slice of the original size at the polled price, with fees."""
        which = part["kind"]
        frac = float(part.get("fraction") or 0)
        orig = float(p.get("original_size_usd") or p["size_usd"] or 0)
        remaining = float(p.get("size_usd") or 0)
        sold = min(orig * frac, remaining)
        if sold <= 1e-9:
            return p
        discount = float(self.settings.get("fees_ref_discount") or 0)
        fees = round_trip_fees(sold, discount)
        net, pct = risk_mod.pnl(float(p["entry_price"]), price, sold, fees)
        new_remaining = remaining - sold
        realized = float(p.get("realized_pnl_usd") or 0) + net
        fees_realized = float(p.get("fees_realized_usd") or 0) + fees
        name = p["name"] or p["symbol"] or p["mint"]
        link = p.get("link") or coin_url(p["mint"], "solana")
        label = self._frac_label(frac)
        tp_pct = float(part.get("pct") or 0)
        mode = p.get("mode") or "PAPER"
        if new_remaining <= 1e-9:
            status = "closed"
            closed_at = datetime.now(timezone.utc).isoformat()
            await self.db.execute(
                "UPDATE positions SET size_usd=?, realized_pnl_usd=?, fees_realized_usd=?,"
                " tp1_hit=?, tp2_hit=?, tp1_price=?, tp2_price=?,"
                " status=?, closed_at=?, exit_price=?, exit_reason=?, pnl_usd=?, fees_usd=?, pct=? WHERE id=?",
                (
                    0, realized, fees_realized,
                    1 if which == "tp1" or p.get("tp1_hit") else 0,
                    1 if which == "tp2" or p.get("tp2_hit") else 0,
                    price if which == "tp1" else p.get("tp1_price"),
                    price if which == "tp2" else p.get("tp2_price"),
                    status, closed_at, price, which, realized, fees_realized, pct, p["id"],
                ),
            )
        else:
            await self.db.execute(
                "UPDATE positions SET size_usd=?, realized_pnl_usd=?, fees_realized_usd=?,"
                f" {which}_hit=1, {which}_price=? WHERE id=?",
                (new_remaining, realized, fees_realized, price, p["id"]),
            )
        bkey = "paper_balance" if mode == "PAPER" else "live_stack"
        self.settings[bkey] = float(self.settings.get(bkey) or 0) + net
        await self.db.save_settings(self.settings)
        sign_n = "+" if net >= 0 else "-"
        text = paper(f"Took {label} profit on {name} · {sign_n}${abs(net):.2f} ({pct:+.2f}%)", mode)
        if self.tg:
            await self.tg.send(text, sell_keyboard(p["mint"]))
        right = f"+${net:.2f}" if net >= 0 else f"-${abs(net):.2f}"
        await self.db.add_activity(
            kind="took_profit", mint=p["mint"], title=f"Took profit {name}",
            agent="Risk", detail=f"+{tp_pct:g}% · {label}",
            right=right, link=link, tone="good" if net >= 0 else "bad", night=self.night,
        )
        logging.getLogger("risk").info(
            "%s %s sold=$%s remaining=$%s net=$%s", p["mint"], which, sold, new_remaining, net,
        )
        if new_remaining <= 1e-9:
            return None
        p = dict(p)
        p["size_usd"] = new_remaining
        p["realized_pnl_usd"] = realized
        p["fees_realized_usd"] = fees_realized
        p[f"{which}_hit"] = 1
        p[f"{which}_price"] = price
        return p

    async def _close_position(self, p: dict, price: float, reason: str) -> None:
        mode = p.get("mode") or "PAPER"
        remaining = float(p["size_usd"] or 0)
        fees = round_trip_fees(remaining, float(self.settings.get("fees_ref_discount") or 0))
        net, pct = risk_mod.pnl(float(p["entry_price"]), price, remaining, fees)
        realized = float(p.get("realized_pnl_usd") or 0)
        fees_realized = float(p.get("fees_realized_usd") or 0)
        total_pnl = realized + net
        total_fees = fees_realized + fees
        name = p["name"] or p["symbol"] or p["mint"]
        link = p.get("link") or coin_url(p["mint"], "solana")
        stop_pct = float(p["stop_pct"])
        if True:
            # close immediately; apply this slice's pnl to simulated balance (partials already booked)
            await self.db.execute(
                "UPDATE positions SET status=?, closed_at=?, exit_price=?, exit_reason=?, "
                "pnl_usd=?, fees_usd=?, pct=?, size_usd=0, realized_pnl_usd=? WHERE id=?",
                ("closed", datetime.now(timezone.utc).isoformat(), price, reason, total_pnl, total_fees, pct, total_pnl, p["id"]),
            )
            bkey = "paper_balance" if mode == "PAPER" else "live_stack"
            self.settings[bkey] = float(self.settings.get(bkey) or 0) + net
            await self.db.save_settings(self.settings)
        # push
        if reason == "trail":
            text = paper(f"Sold {name} · +${net:.2f} ({pct:+.2f}%)" if net >= 0 else f"Sold {name} · ${net:.2f} ({pct:+.2f}%)", mode)
            # specified: "Sold {name} · +${pnl} (+{pct}%)"
            sign_n = "+" if net >= 0 else ""
            sign_p = "+" if pct >= 0 else ""
            text = paper(f"Sold {name} · {sign_n}${abs(net):.2f} ({sign_p}{pct:.2f}%)", mode) if net >= 0 else paper(f"Sold {name} · -${abs(net):.2f} ({pct:.2f}%)", mode)
        elif reason == "stop":
            text = paper(f"{name} hit the -{stop_pct:g}% stop · -${abs(net):.2f}", mode)
        elif reason == "timeout":
            text = paper(f"Sell {name}, dead money · {pct:.2f}% in {self.settings['timeout_h']:g}h", mode)
        else:
            text = paper(f"Sell {name}, {reason}", mode)
        if self.tg:
            await self.tg.send(text, sell_keyboard(p["mint"]))
        tone = "good" if net >= 0 and reason != "stop" else "bad"
        kind = {"trail": "sold", "stop": "stopped", "timeout": "timeout", "pulled": "pulled"}.get(reason, "sold")
        title = f"Sold {name}" if kind == "sold" else (f"Stopped {name}" if kind == "stopped" else f"{name}")
        detail = {
            "trail": "Risk · trailing stop",
            "stop": f"Risk · -{stop_pct:g}% stop",
            "timeout": "Risk · timeout",
            "pulled": "Risk · pulled",
        }.get(reason, reason)
        right = f"+${net:.2f}" if net >= 0 else f"-${abs(net):.2f}"
        await self.db.add_activity(
            kind=kind, mint=p["mint"], title=title, agent="Risk",
            detail=detail, right=f"{right} / {pct:+.2f}%", link=link, tone=tone, night=self.night,
        )

    # ----- telegram -----
    async def telegram_loop(self) -> None:
        while self.running:
            await self.beat("telegram")
            if not self.tg or not self.tg.ok:
                await asyncio.sleep(5)
                continue
            try:
                updates = await self.tg.get_updates(timeout=25)
            except Exception:
                log.exception("telegram poll")
                await asyncio.sleep(3)
                continue
            for u in updates:
                await self._maybe_register_channel(u)
                msg = u.get("message") or u.get("edited_message") or {}
                chat = str((msg.get("chat") or {}).get("id") or "")
                if chat != str(self.tg.owner):
                    continue
                text = msg.get("text") or ""
                if not text:
                    continue
                try:
                    reply, kb = await cmds.handle(self, text)
                except Exception:
                    log.exception("command")
                    reply, kb = "Something went wrong on that command.", None
                await self.tg.send(reply, kb)

    async def _maybe_register_channel(self, u: dict) -> None:
        """Remember the signal channel when the bot is made admin there, or the owner forwards a channel post."""
        from notify import save_channel_id, load_channel_id
        cid, title = None, None
        mcm = u.get("my_chat_member") or {}
        chat = mcm.get("chat") or {}
        if chat.get("type") == "channel" and (mcm.get("new_chat_member") or {}).get("status") == "administrator":
            cid, title = chat.get("id"), chat.get("title")
        msg = u.get("message") or {}
        if str((msg.get("chat") or {}).get("id") or "") == str(self.tg.owner):
            fc = msg.get("forward_from_chat") or ((msg.get("forward_origin") or {}).get("chat")) or {}
            if fc.get("type") == "channel":
                cid, title = fc.get("id"), fc.get("title")
        cp = u.get("channel_post") or {}
        if cp and not load_channel_id() and (cp.get("chat") or {}).get("type") == "channel":
            cid, title = cp["chat"].get("id"), cp["chat"].get("title")
        if cid and str(cid) != str(load_channel_id() or ""):
            save_channel_id(str(cid))
            await self.tg.send(f"Kanal verbunden: {title or cid}. Kaufsignale gehen ab jetzt auch dorthin.")

    async def _send_channel_buy(self, name: str, mint: str, size: float, stack_pct: float) -> None:
        from notify import load_channel_id
        cid = load_channel_id()
        if not cid or not self.tg:
            return
        try:
            await self.tg.send_to(cid, f"🟢 Kaufsignal · {name} · ${size:.2f} ({stack_pct:.0f}% vom Stack)", buy_keyboard(mint))
        except Exception:
            log.exception("channel send")

    # ----- publisher -----
    async def publisher_loop(self) -> None:
        while self.running:
            await self.beat("publisher")
            try:
                await self.publish_now()
                await asyncio.to_thread(publish)
            except Exception:
                log.exception("publish")
            await asyncio.sleep(60)

    async def night_rollover(self) -> None:
        while self.running:
            n = current_night(self.settings.get("report_time") or "08:00")
            if n != self.night:
                self.night = n
                self.seen_mints.clear()
                self.pushed_tonight.clear()
                await self.db.execute(
                    "INSERT OR IGNORE INTO night_meta(night, started_at, paper_complete) VALUES(?,?,0)",
                    (self.night, datetime.now(timezone.utc).isoformat()),
                )
                await self.ticket_announce()
            await asyncio.sleep(30)


async def amain() -> None:
    _setup_logging()
    PID_FILE.write_text(str(os.getpid()) + "\n")
    desk = Desk()
    await desk.start()
    log.info("desk up mode=%s night=%s", desk.settings.get("mode"), desk.night)
    tasks = [
        asyncio.create_task(desk.scanner_ws(), name="scanner_ws"),
        asyncio.create_task(desk.scanner_poll(), name="scanner_poll"),
        asyncio.create_task(desk.auditor_loop(), name="auditor"),
        asyncio.create_task(desk.analyst_loop(), name="analyst"),
        asyncio.create_task(desk.brain_loop(), name="brain"),
        asyncio.create_task(desk.executor_loop(), name="executor"),
        asyncio.create_task(desk.risk_loop(), name="risk"),
        asyncio.create_task(desk.telegram_loop(), name="telegram"),
        asyncio.create_task(desk.publisher_loop(), name="publisher"),
        asyncio.create_task(desk.night_rollover(), name="night"),
    ]
    stop = asyncio.Event()

    def _stop(*_):
        stop.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            pass
    await stop.wait()
    desk.running = False
    for t in tasks:
        t.cancel()
    await desk.close()
    log.info("desk down")


if __name__ == "__main__":
    try:
        asyncio.run(amain())
    finally:
        if PID_FILE.exists():
            try:
                PID_FILE.unlink()
            except OSError:
                pass
