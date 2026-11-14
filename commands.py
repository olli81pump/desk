"""STEP 9 Telegram (and in-app) commands. Owner only. Never places an order."""

from __future__ import annotations

import re
from typing import Any

from links import SIGNUP_URL, coin_url
from notify import paper, buy_keyboard, sell_keyboard
import settings as S

HELP = (
    "Commands:\n"
    "buy X\n"
    "sell X\n"
    "why X\n"
    "pause Scanner  (or resume Auditor, …)\n"
    "set stop to -8%\n"
    "stack 1240\n"
    "status\n"
    "paper | live\n"
    "invite\n"
    "report\n"
    "X can be a name, symbol or mint."
)


def parse(text: str) -> tuple[str, str]:
    t = (text or "").strip()
    if t.startswith("/"):
        t = t[1:]
    t = re.sub(r"@\w+", "", t).strip()
    if not t:
        return "help", ""
    low = t.lower()
    if low in {"help", "start", "commands"}:
        return "help", ""
    if low in {"status"}:
        return "status", ""
    if low in {"paper"}:
        return "paper", ""
    if low in {"live", "live live"}:
        return "live", t
    if low in {"invite"}:
        return "invite", ""
    if low in {"report"}:
        return "report", ""
    m = re.match(r"^(buy|sell|why)\s+(.+)$", t, re.I)
    if m:
        return m.group(1).lower(), m.group(2).strip()
    m = re.match(r"^(pause|resume)\s+(.+)$", t, re.I)
    if m:
        return m.group(1).lower(), m.group(2).strip()
    m = re.match(r"^stack\s+([0-9]+(?:[.,][0-9]+)?)$", t, re.I)
    if m:
        return "stack", m.group(1).replace(",", ".")
    m = re.match(r"^set\s+(.+?)\s+to\s+(.+)$", t, re.I)
    if m:
        return "set", f"{m.group(1).strip()}={m.group(2).strip()}"
    m = re.match(r"^set\s+(\S+)\s+(.+)$", t, re.I)
    if m:
        return "set", f"{m.group(1).strip()}={m.group(2).strip()}"
    return "unknown", t


def agent_name(raw: str) -> str | None:
    n = raw.strip().lower()
    aliases = {
        "scanner": "scanner", "1": "scanner",
        "auditor": "auditor", "2": "auditor",
        "analyst": "analyst", "3": "analyst",
        "brain": "brain",
        "executor": "executor", "4": "executor",
        "risk": "risk", "5": "risk",
    }
    return aliases.get(n)


async def resolve_coins(db, q: str) -> list:
    return await db.find_coins(q)


def coin_line(c) -> str:
    mint = c["mint"] if not isinstance(c, dict) else c["mint"]
    name = (c["name"] if not isinstance(c, dict) else c.get("name")) or mint
    sym = (c["symbol"] if not isinstance(c, dict) else c.get("symbol")) or ""
    label = f"{name} ({sym})" if sym else name
    return f"{label} — {coin_url(mint, 'solana')}"


async def handle(desk, text: str) -> tuple[str, dict | None]:
    """Return (reply_text, optional_keyboard)."""
    cmd, arg = parse(text)
    if cmd == "help" or cmd == "unknown":
        extra = "" if cmd == "help" else "Unknown text.\n\n"
        return extra + HELP, None
    if cmd == "invite":
        return SIGNUP_URL, None
    if cmd == "report":
        url = await desk.db.get_kv("last_report_url")
        return (url or "No morning report yet."), None
    if cmd == "status":
        return await cmd_status(desk)
    if cmd == "paper":
        s = desk.settings
        if s.get("mode") == "PAPER":
            return "Already in PAPER.", None
        s["mode"] = "PAPER"
        await desk.db.save_settings(s)
        return "Switched to PAPER.", None
    if cmd == "live":
        return await cmd_live(desk, arg)
    if cmd == "stack":
        try:
            val = float(arg)
        except ValueError:
            return "stack needs a number, e.g. stack 1240", None
        err = S.validate("live_stack", val)
        if err:
            return err, None
        desk.settings["live_stack"] = val
        await desk.db.save_settings(desk.settings)
        return f"LIVE stack set to ${val:.2f}", None
    if cmd == "set":
        return await cmd_set(desk, arg)
    if cmd in {"pause", "resume"}:
        return await cmd_pause(desk, cmd, arg)
    if cmd in {"buy", "sell", "why"}:
        coins = await resolve_coins(desk.db, arg)
        if not coins:
            # might be a raw mint not in db
            if re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", arg):
                if cmd == "buy":
                    return await cmd_buy_unknown_mint(desk, arg)
                return "I don't know that coin yet. Send me the mint if this is a new one.", None
            return "I don't know that name or symbol. Send me the mint.", None
        if len(coins) > 1:
            lines = ["Which one?"]
            for c in coins[:8]:
                lines.append(coin_line(c))
            return "\n".join(lines), None
        c = coins[0]
        if cmd == "buy":
            return await cmd_buy(desk, c)
        if cmd == "sell":
            return await cmd_sell(desk, c)
        return await cmd_why(desk, c)
    return HELP, None


async def cmd_status(desk) -> tuple[str, dict | None]:
    s = desk.settings
    mode = s.get("mode") or "PAPER"
    bal = s.get("paper_balance") if mode == "PAPER" else s.get("live_stack")
    lines = [paper(f"mode {mode}") if mode == "PAPER" else f"mode {mode}", f"balance ${float(bal or 0):.2f}"]
    poss = await desk.db.open_positions()
    if not poss:
        lines.append("no open positions")
        return "\n".join(lines), None
    kb_rows = []
    for p in poss:
        name = p["name"] or p["symbol"] or p["mint"]
        orig = p["original_size_usd"] if "original_size_usd" in p.keys() and p["original_size_usd"] else p["size_usd"]
        rem = p["size_usd"]
        bits = [f"{name}  remaining ${float(rem or 0):.2f} of ${float(orig or 0):.2f}"]
        if p["tp1_hit"] if "tp1_hit" in p.keys() else False:
            bits.append("TP1 hit")
        if p["tp2_hit"] if "tp2_hit" in p.keys() else False:
            bits.append("TP2 hit")
        bits.append(f"entry {p['entry_price']}")
        bits.append(coin_url(p["mint"], "solana"))
        lines.append("  ".join(bits))
        kb_rows.append([{"text": f"Sell {p['symbol'] or name} on FOMO", "url": coin_url(p["mint"], "solana")}])
    return "\n".join(lines), {"inline_keyboard": kb_rows}


async def cmd_live(desk, arg: str) -> tuple[str, dict | None]:
    if arg.strip() != "LIVE" and arg.strip().lower() != "live live":
        # Switching to LIVE needs the user to type LIVE
        return "To switch to LIVE, type LIVE.", None
    # also the typed command might just be "live" — require exact LIVE
    if arg.strip() != "LIVE":
        return "To switch to LIVE, type LIVE (all caps).", None
    night_ok = await desk.db.fetchone("SELECT night FROM night_meta WHERE paper_complete=1 LIMIT 1")
    if not night_ok:
        return "LIVE needs at least one full PAPER night in the db first.", None
    desk.settings["mode"] = "LIVE"
    await desk.db.save_settings(desk.settings)
    return "Switched to LIVE. Money only moves when you tap Buy on FOMO.", None


async def cmd_set(desk, arg: str) -> tuple[str, dict | None]:
    if "=" not in arg:
        return "Try: set stop to -8%", None
    name, raw = arg.split("=", 1)
    key = S.resolve_alias(name)
    if not key:
        return f"Unknown setting '{name}'.", None
    try:
        val = S.parse_value(key, raw)
    except Exception as e:
        return f"Could not read that value ({e}).", None
    err = S.validate(key, val)
    if err:
        rng = S.RANGES.get(key)
        extra = f" Range {rng[0]}–{rng[1]}." if rng else ""
        return err + extra, None
    if key == "mode":
        return "Use the paper / live commands to change mode.", None
    old = desk.settings.get(key)
    # stop loosening must not move open stops down — applied in risk when a position is opened
    desk.settings[key] = val
    await desk.db.save_settings(desk.settings)
    if key in {"stack_pct", "below_min", "min_ticket_usd", "min_size_usd", "max_size_usd", "paper_start_stack"}:
        await desk.ticket_announce()
    return S.format_change(key, old, val), None


async def cmd_pause(desk, cmd: str, arg: str) -> tuple[str, dict | None]:
    agent = agent_name(arg)
    if not agent:
        return "Name one of: Scanner, Auditor, Analyst, Brain, Executor, Risk.", None
    paused = await desk.db.get_kv("paused", {}) or {}
    if cmd == "pause" and agent == "risk":
        openp = await desk.db.open_positions()
        if openp:
            return "Risk can't be paused while a position is open.", None
    paused[agent] = cmd == "pause"
    await desk.db.set_kv("paused", paused)
    return f"{'Paused' if cmd == 'pause' else 'Resumed'} {agent.title()}.", None


async def cmd_buy(desk, c) -> tuple[str, dict | None]:
    mint = c["mint"]
    # if already pushed tonight, resend
    night = desk.night
    row = await desk.db.fetchone(
        "SELECT * FROM executions WHERE mint=? AND status IN ('sent','bought') ORDER BY id DESC LIMIT 1",
        (mint,),
    )
    name = c["name"] or c["symbol"] or mint
    if row:
        text = paper(f"{name} — already pushed tonight")
        return text, buy_keyboard(mint)
    # run Auditor now, not sized, not on the desk
    result = await desk.audit_now(mint)
    lines = [f"Auditor on {name}", coin_url(mint, "solana")]
    for L in result.get("layers") or []:
        mark = "ok" if L.get("pass") is True else ("red" if L.get("pass") is False else "—")
        lines.append(f"{L['n']}. {L['name']}: {mark} · {L.get('value')}")
    lines.append("not sized, not on the desk")
    return "\n".join(lines), buy_keyboard(mint)


async def cmd_buy_unknown_mint(desk, mint: str) -> tuple[str, dict | None]:
    await desk.db.upsert_coin(mint=mint, night=desk.night, coin_url=coin_url(mint, "solana"), status="lookup")
    result = await desk.audit_now(mint)
    lines = [f"Auditor on {mint}", coin_url(mint, "solana")]
    for L in result.get("layers") or []:
        mark = "ok" if L.get("pass") is True else ("red" if L.get("pass") is False else "—")
        lines.append(f"{L['n']}. {L['name']}: {mark} · {L.get('value')}")
    lines.append("not sized, not on the desk")
    return "\n".join(lines), buy_keyboard(mint)


async def cmd_sell(desk, c) -> tuple[str, dict | None]:
    mint = c["mint"]
    pos = await desk.db.position_for_mint(mint)
    name = c["name"] or c["symbol"] or mint
    if not pos:
        return f"No open position in {name} {coin_url(mint, 'solana')}", None
    return paper(f"Sell {name}"), sell_keyboard(mint)


async def cmd_why(desk, c) -> tuple[str, dict | None]:
    mint = c["mint"]
    name = c["name"] or c["symbol"] or mint
    link = coin_url(mint, "solana")
    # latest decision in order: executor skip, analyst reject, auditor red, scanner kill
    ex = await desk.db.fetchone("SELECT * FROM executions WHERE mint=? ORDER BY id DESC LIMIT 1", (mint,))
    if ex and ex["status"] in {"skipped", "missed"}:
        return f"{name} stopped by Executor · {ex['reason']} · {ex['ts']}\n{link}", None
    an = await desk.db.fetchone("SELECT * FROM analyses WHERE mint=? ORDER BY id DESC LIMIT 1", (mint,))
    if an and not an["passed"]:
        return f"{name} stopped by Analyst (rules) · {an['failed']} · {an['ts']}\n{link}", None
    au = await desk.db.fetchone("SELECT * FROM audits WHERE mint=? ORDER BY id DESC LIMIT 1", (mint,))
    if au and not au["passed"]:
        # find red layer
        import json
        layers = json.loads(au["layers"] or "[]")
        red = next((L for L in layers if L.get("pass") is False), None)
        layer = f"layer {red['n']} {red['name']}" if red else "auditor"
        val = (red or {}).get("value") or au["reason"]
        return f"{name} stopped by Auditor · {layer} · {val} · {au['ts']}\n{link}", None
    sc = await desk.db.fetchone("SELECT * FROM scans WHERE mint=? ORDER BY id DESC LIMIT 1", (mint,))
    if sc and sc["verdict"] == "kill":
        return f"{name} stopped by Scanner · {sc['reason']} · {sc['ts']}\n{link}", None
    if sc and sc["verdict"] == "pass":
        return f"{name} passed Scanner, no later stop in the db.\n{link}", None
    return f"I have no decision on {name} yet.\n{link}", None
