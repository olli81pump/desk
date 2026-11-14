"""Performance statistics for the public state.json (read-only, no secrets)."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

BERLIN = ZoneInfo("Europe/Berlin")
EXIT_KEYS = ["stop", "tp1", "tp2", "trail", "timeout", "manual", "pulled"]
MIN_TRADES = 10


def _dt(s):
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _day(s) -> str | None:
    d = _dt(s)
    return d.astimezone(BERLIN).date().isoformat() if d else None


def reason_label(reason: str | None) -> str:
    """Group raw kill/reject reasons into stable German categories."""
    r = (reason or "").strip().lower()
    if not r:
        return "Unbekannt"
    if r.startswith("liq ") or r.startswith("liq$"):
        return "Liquidität zu niedrig"
    if r == "never qualified":
        return "Nie qualifiziert"
    if "bundled" in r or "bundles" in r:
        return "Gebündelte Wallets"
    if r.startswith("top 10") or "top 10" in r:
        return "Top-10 zu konzentriert" if "hold" in r else "Keine Daten: Top-10"
    if "in 1h" in r:
        return "Schon zu stark gestiegen (1h)"
    if r.startswith("no data"):
        return "Keine Daten: " + r.split(":", 1)[-1].strip()
    if "mint not revoked" in r:
        return "Mint-Authority aktiv"
    if "freeze" in r:
        return "Freeze-Authority aktiv"
    if r.startswith("dev") or "supply" in r:
        return "Dev-Wallet"
    if "liquidity" in r:
        return "Liquidität nicht gesperrt"
    if "too young" in r:
        return "Pool zu jung"
    if "delegat" in r:
        return "Delegationen"
    if r.startswith("score"):
        return "Score zu niedrig"
    if r.startswith(("alive_6h", "organic", "chase")):
        return "Analyst-Regel: " + r.split()[0]
    if r.startswith("size $"):
        return "Größe unter Minimum"
    if r in {"no price", "price ran", "liquidity dropped"}:
        return {"no price": "Kein Preis", "price ran": "Preis davongelaufen",
                "liquidity dropped": "Liquidität gefallen"}[r]
    if "copy" in r:
        return "Kopie eines Runners"
    return re.sub(r"[\$\d][\d.,]*[kKmM%]?", "#", reason or "").strip() or "Unbekannt"


def _summary(trades: list[dict], start_stack: float | None) -> dict:
    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    gross_w = sum(wins)
    gross_l = -sum(losses)
    # equity / drawdown on cumulative PnL (start = 0, or start stack if known)
    base = float(start_stack or 0)
    eq, peak, mdd, mdd_pct = base, base, 0.0, 0.0
    for p in pnls:
        eq += p
        peak = max(peak, eq)
        dd = peak - eq
        if dd > mdd:
            mdd = dd
            mdd_pct = (dd / peak * 100) if (peak > 0 and start_stack is not None) else 0.0
    holds = []
    for t in trades:
        a, b = _dt(t.get("opened_at")), _dt(t.get("closed_at"))
        if a and b:
            holds.append((b - a).total_seconds() / 60)
    best = max(trades, key=lambda t: t["pnl"]) if trades else None
    worst = min(trades, key=lambda t: t["pnl"]) if trades else None
    pick = lambda t: ({"name": t["name"], "pnl": round(t["pnl"], 2), "pct": t["pct"], "link": t["link"]} if t else None)
    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(trades) * 100, 1) if trades else None,
        "pnl": round(sum(pnls), 2),
        "fees": round(sum(t["fees"] for t in trades), 2),
        "avg_win": round(gross_w / len(wins), 2) if wins else None,
        "avg_loss": round(-gross_l / len(losses), 2) if losses else None,
        "profit_factor": (round(gross_w / gross_l, 2) if gross_l > 0 else (None if not wins else "inf")),
        "expectancy": round(sum(pnls) / len(pnls), 2) if pnls else None,
        "best": pick(best),
        "worst": pick(worst),
        "max_dd": round(mdd, 2),
        "max_dd_pct": round(mdd_pct, 1),
        "avg_hold_min": round(sum(holds) / len(holds), 1) if holds else None,
        "start_stack": round(base, 2) if start_stack is not None else None,
    }


async def build_stats(db, s: dict, coin_url) -> dict:
    rows = await db.fetchall(
        "SELECT * FROM positions WHERE status='closed' AND closed_at IS NOT NULL ORDER BY closed_at"
    )
    trades = []
    for r in rows:
        r = {k: r[k] for k in r.keys()}
        mint = r.get("mint")
        trades.append({
            "id": r.get("id"),
            "mode": r.get("mode") or "PAPER",
            "name": r.get("name") or r.get("symbol") or (mint or "")[:6],
            "mint": mint,
            "link": r.get("link") or (coin_url(mint, "solana") if mint else None),
            "opened_at": r.get("opened_at"),
            "closed_at": r.get("closed_at"),
            "size": round(float(r.get("original_size_usd") or r.get("size_usd") or 0), 2),
            "pnl": float(r.get("pnl_usd") or 0),
            "fees": float(r.get("fees_usd") or 0),
            "pct": round(float(r.get("pct") or 0), 2),
            "reason": r.get("exit_reason") or "manual",
            "tp1": bool(r.get("tp1_hit")),
            "tp2": bool(r.get("tp2_hit")),
        })

    paper_start = s.get("paper_start_stack")
    # LIVE start = current live stack minus booked LIVE PnL
    live_pnl = sum(t["pnl"] for t in trades if t["mode"] == "LIVE")
    live_start = (float(s.get("live_stack") or 0) - live_pnl) if s.get("live_stack") is not None else None
    starts = {"PAPER": paper_start, "LIVE": live_start}

    today = datetime.now(BERLIN).date().isoformat()
    by_mode: dict[str, dict] = {}
    for m in ("ALL", "LIVE", "PAPER"):
        ts = [t for t in trades if m == "ALL" or t["mode"] == m]
        summ = _summary(ts, starts.get(m))
        cum, eq = 0.0, []
        for t in ts:
            cum += t["pnl"]
            eq.append({"ts": t["closed_at"], "v": round(cum, 2)})
        daily = defaultdict(lambda: {"pnl": 0.0, "n": 0})
        for t in ts:
            d = _day(t["closed_at"])
            daily[d]["pnl"] += t["pnl"]
            daily[d]["n"] += 1
        exits = Counter(t["reason"] for t in ts)
        exit_rows = []
        for k in EXIT_KEYS + sorted(set(exits) - set(EXIT_KEYS)):
            sub = [t for t in ts if t["reason"] == k]
            exit_rows.append({"reason": k, "n": exits.get(k, 0), "pnl": round(sum(t["pnl"] for t in sub), 2)})
        summ.update({
            "equity": eq,
            "daily": [{"day": d, "pnl": round(v["pnl"], 2), "n": v["n"]} for d, v in sorted(daily.items()) if d],
            "exits": exit_rows,
            "tp1_hits": sum(1 for t in ts if t["tp1"]),
            "tp2_hits": sum(1 for t in ts if t["tp2"]),
            "today_pnl": round(sum(t["pnl"] for t in ts if _day(t["closed_at"]) == today), 2),
            "enough": len(ts) >= MIN_TRADES,
        })
        by_mode[m] = summ

    async def n(sql: str) -> int:
        row = await db.fetchone(sql)
        return int(row["n"] if row and row["n"] is not None else 0)

    funnel = [
        {"key": "seen", "label": "Gesehen", "n": await n("SELECT COUNT(*) n FROM coins")},
        {"key": "scanned", "label": "Gescannt", "n": await n("SELECT COUNT(DISTINCT mint) n FROM scans")},
        {"key": "scan_pass", "label": "Scanner ok", "n": await n("SELECT COUNT(DISTINCT mint) n FROM scans WHERE verdict='pass'")},
        {"key": "audited", "label": "Auditiert", "n": await n("SELECT COUNT(DISTINCT mint) n FROM audits")},
        {"key": "audit_pass", "label": "Audit 8/8", "n": await n("SELECT COUNT(DISTINCT mint) n FROM audits WHERE passed=1")},
        {"key": "scored", "label": "Bewertet", "n": await n("SELECT COUNT(DISTINCT mint) n FROM analyses")},
        {"key": "score_pass", "label": "Score ok", "n": await n("SELECT COUNT(DISTINCT mint) n FROM analyses WHERE passed=1")},
        {"key": "signaled", "label": "Signal/Kauf", "n": await n("SELECT COUNT(*) n FROM positions")},
    ]

    rej = Counter()
    stage_of = {}
    for r in await db.fetchall("SELECT reason FROM scans WHERE verdict='kill'"):
        lab = reason_label(r["reason"]); rej[lab] += 1; stage_of.setdefault(lab, "Scanner")
    for r in await db.fetchall("SELECT reason FROM audits WHERE passed=0"):
        lab = reason_label(r["reason"]); rej[lab] += 1; stage_of.setdefault(lab, "Auditor")
    for r in await db.fetchall("SELECT failed FROM analyses WHERE passed=0"):
        try:
            failed = json.loads(r["failed"] or "[]")
        except Exception:
            failed = []
        for f in failed[:1]:
            lab = reason_label(f); rej[lab] += 1; stage_of.setdefault(lab, "Analyst")
    for r in await db.fetchall("SELECT reason FROM brains WHERE skipped=1"):
        lab = reason_label(r["reason"]); rej[lab] += 1; stage_of.setdefault(lab, "Brain")
    rejections = [{"label": k, "n": v, "agent": stage_of.get(k)} for k, v in rej.most_common(8)]

    recent = [
        {k: (round(v, 2) if isinstance(v, float) else v) for k, v in t.items() if k in
         ("mode", "name", "link", "opened_at", "closed_at", "size", "pnl", "pct", "reason", "fees")}
        for t in reversed(trades[-25:])
    ]
    return {
        "generated": datetime.now(timezone.utc).isoformat(),
        "min_trades": MIN_TRADES,
        "modes": by_mode,
        "funnel": funnel,
        "rejections": rejections,
        "recent": recent,
    }
