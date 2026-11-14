"""Build the public state.json (no secrets)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from links import SIGNUP_URL, coin_url, profile_url


def _row(r) -> dict:
    if r is None:
        return {}
    if isinstance(r, dict):
        return dict(r)
    return {k: r[k] for k in r.keys()}


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def build(db, s: dict, extra: dict | None = None) -> dict:
    night = extra.get("night") if extra else None
    paused = await db.get_kv("paused", {}) or {}
    hb = await db.heartbeats()
    positions = [_pos(_row(p)) for p in await db.open_positions()]
    # recent activity
    acts = await db.fetchall("SELECT * FROM activity ORDER BY id DESC LIMIT 200")
    activity = [_act(_row(a)) for a in acts]
    # agent cards
    scans_n = await _count(db, "SELECT COUNT(*) n FROM scans")
    passed_n = await _count(db, "SELECT COUNT(*) n FROM scans WHERE verdict='pass'")
    killed_n = await _count(db, "SELECT COUNT(*) n FROM scans WHERE verdict='kill'")
    audits_n = await _count(db, "SELECT COUNT(*) n FROM audits")
    rejected_a = await _count(db, "SELECT COUNT(*) n FROM audits WHERE passed=0")
    analyses_n = await _count(db, "SELECT COUNT(*) n FROM analyses")
    trades_n = await _count(db, "SELECT COUNT(*) n FROM positions")
    waiting = await db.fetchall("SELECT w.mint, c.name, c.symbol, c.pool, w.added_at FROM waiting w LEFT JOIN coins c ON c.mint=w.mint")

    scan_feed = []
    for row in await db.fetchall("SELECT * FROM scans ORDER BY id DESC LIMIT 40"):
        r = _row(row)
        payload = _json(r.get("payload"))
        scan_feed.append({
            "mint": r.get("mint"),
            "name": payload.get("name") or r.get("mint"),
            "symbol": payload.get("symbol"),
            "verdict": r.get("verdict"),
            "reason": r.get("reason"),
            "liq": payload.get("liquidityUsd"),
            "link": coin_url(r.get("mint"), "solana") if r.get("mint") else SIGNUP_URL,
            "ts": r.get("ts"),
        })

    latest_audit = None
    arow = await db.fetchone("SELECT * FROM audits ORDER BY id DESC LIMIT 1")
    if arow:
        latest_audit = _audit(_row(arow))

    coins_out = {}
    for row in await db.fetchall("SELECT * FROM coins ORDER BY seen_at DESC LIMIT 80"):
        c = _row(row)
        mint = c["mint"]
        coins_out[mint] = await _coin_pack(db, c, s)

    mode = s.get("mode") or "PAPER"
    stack = float(s["paper_balance"] if mode == "PAPER" else (s.get("live_stack") or 0) or 0)
    ticket = extra.get("ticket") if extra else None

    return {
        "mode": mode,
        "ts": iso_now(),
        "balance": stack if mode == "PAPER" else s.get("live_stack"),
        "stack": stack,
        "fomo_handle": s.get("fomo_handle") or "olli81",
        "signup_url": SIGNUP_URL,
        "profile_url": profile_url(s.get("fomo_handle") or "olli81"),
        "notifier": "telegram",
        "notifier_note": "Web-Push ist in Plan B nicht verfügbar. Meldungen kommen über Telegram.",
        "settings": _public_settings(s),
        "paused": paused,
        "heartbeats": hb,
        "ticket_warning": (ticket or {}).get("warning"),
        "report_url": await db.get_kv("last_report_url"),
        "positions": positions,
        "activity": activity,
        "waiting": [_row(w) | {"link": coin_url(w["mint"], "solana")} for w in waiting],
        "coins": coins_out,
        "latest_audit": latest_audit,
        "agents": {
            "scanner": {
                "name": "Scanner",
                "card": f"{len(waiting)} pools",
                "sub": f"{passed_n} passed · {killed_n} killed",
                "paused": bool(paused.get("scanner")),
                "heartbeat": hb.get("scanner"),
                "feed": scan_feed,
            },
            "auditor": {
                "name": "Auditor",
                "card": f"{audits_n} taken apart",
                "sub": f"{rejected_a} rejected" if rejected_a else "idle",
                "paused": bool(paused.get("auditor")),
                "heartbeat": hb.get("auditor"),
                "latest": latest_audit,
            },
            "analyst": {
                "name": "Analyst",
                "card": "Scoring",
                "sub": f"mode rules · {analyses_n} scored",
                "paused": bool(paused.get("analyst")),
                "heartbeat": hb.get("analyst"),
                "min_score": s.get("min_score"),
                "last": await _last_analysis(db),
            },
            "executor": {
                "name": "Executor",
                "card": f"{trades_n} trades",
                "sub": f"{s.get('stack_pct')}% of stack",
                "paused": bool(paused.get("executor")),
                "heartbeat": hb.get("executor"),
            },
            "risk": {
                "name": "Risk",
                "card": "Guarding" if positions else "Idle",
                "sub": _last_exit_label(activity),
                "paused": bool(paused.get("risk")),
                "heartbeat": hb.get("risk"),
                "pills": {
                    "stop": f"stop -{s.get('stop_pct')}%",
                    "trail": f"trail {s.get('trail_pct')}%",
                },
            },
        },
    }


def _public_settings(s: dict) -> dict:
    skip = {"live_stack"}  # keep shown but it's fine; no secrets in settings
    return {k: v for k, v in s.items() if k not in skip}


async def _count(db, sql: str) -> int:
    row = await db.fetchone(sql)
    return int(row["n"] if row else 0)


def _pos(p: dict) -> dict:
    mint = p.get("mint")
    return {
        "id": p.get("id"),
        "mint": mint,
        "name": p.get("name"),
        "symbol": p.get("symbol"),
        "status": p.get("status"),
        "mode": p.get("mode"),
        "opened_at": p.get("opened_at"),
        "entry_price": p.get("entry_price"),
        "peak_price": p.get("peak_price"),
        "size_usd": p.get("size_usd"),
        "stop_pct": p.get("stop_pct"),
        "trail_active": bool(p.get("trail_active")),
        "link": p.get("link") or coin_url(mint, "solana"),
        "pnl_usd": p.get("pnl_usd"),
        "pct": p.get("pct"),
    }


def _act(a: dict) -> dict:
    mint = a.get("mint")
    return {
        "ts": a.get("ts"),
        "kind": a.get("kind"),
        "mint": mint,
        "title": a.get("title"),
        "agent": a.get("agent"),
        "detail": a.get("detail"),
        "right": a.get("right"),
        "link": a.get("link") or (coin_url(mint, "solana") if mint else None),
        "tone": a.get("tone"),
    }


def _audit(a: dict) -> dict:
    layers = a.get("layers")
    if isinstance(layers, str):
        layers = _json(layers)
    payload = _json(a.get("payload"))
    return {
        "mint": a.get("mint"),
        "ts": a.get("ts"),
        "passed": bool(a.get("passed")),
        "reason": a.get("reason"),
        "holders": a.get("holders"),
        "layers": layers or payload.get("layers") or [],
        "link": coin_url(a.get("mint"), "solana") if a.get("mint") else SIGNUP_URL,
        "name": (payload or {}).get("name"),
    }


async def _coin_pack(db, c: dict, s: dict) -> dict:
    mint = c["mint"]
    prices = await db.prices(mint, limit=240)
    pts = [{"ts": r["ts"], "price": r["price"], "v": r["volume_m5"]} for r in reversed(list(prices))]
    audit_row = await db.latest_audit(mint)
    pos = await db.position_for_mint(mint)
    return {
        "mint": mint,
        "name": c.get("name"),
        "symbol": c.get("symbol"),
        "pool": c.get("pool"),
        "status": c.get("status"),
        "migrated_at": c.get("migrated_at"),
        "link": c.get("coin_url") or coin_url(mint, "solana"),
        "prices": pts,
        "audit": _audit(_row(audit_row)) if audit_row else None,
        "position": _pos(_row(pos)) if pos else None,
        "stop_pct": (pos["stop_pct"] if pos else s.get("stop_pct")),
    }


async def _last_analysis(db):
    row = await db.fetchone("SELECT * FROM analyses ORDER BY id DESC LIMIT 1")
    if not row:
        return None
    r = _row(row)
    payload = _json(r.get("payload"))
    return {
        "mint": r.get("mint"),
        "score": r.get("score"),
        "passed": bool(r.get("passed")),
        "failed": _json(r.get("failed")) if isinstance(r.get("failed"), str) else r.get("failed"),
        "model": payload.get("model") or "rules",
        "link": coin_url(r.get("mint"), "solana") if r.get("mint") else None,
    }


def _last_exit_label(activity: list[dict]) -> str:
    for a in activity:
        if a.get("kind") in {"sold", "stopped", "trailed", "timeout", "pulled"}:
            if a.get("kind") == "stopped":
                return "Stopped"
            if a.get("kind") in {"sold", "trailed"}:
                return "Trailed out"
            return a.get("title") or a.get("kind")
    return "No exits yet"


def _json(v):
    if v is None:
        return {}
    if isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v)
    except Exception:
        return {}
