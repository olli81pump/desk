#!/usr/bin/env python3
"""Daily night report at settings.report_time (default 08:00 Europe/Berlin).

Builds a Markdown + JSON report the Grok Bot routine can turn into a Page.
Does not create the routine or the Page itself. Clears db.skips after writing.
Footer includes SIGNUP_URL. Every coin is linked with coin_url (r=olli81).
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from db import DB, current_night
from links import SIGNUP_URL, coin_url
from notify import Telegram, paper


def link(mint, name=None):
    label = name or mint
    return f"[{label}]({coin_url(mint, 'solana')})"


async def main() -> int:
    db = await DB().open()
    s = await db.load_settings()
    # The night that just ended is the current_night minus the fact we're at report time.
    night = current_night(s.get("report_time") or "08:00")
    # If we run at 08:00, current_night has already rolled to the new day.
    # Use the most recently started night_meta that is not marked complete, else yesterday's key in activity.
    row = await db.fetchone(
        "SELECT night FROM night_meta WHERE paper_complete=0 ORDER BY started_at DESC LIMIT 1"
    )
    if row:
        night = row["night"]

    def is_night(sql, extra=""):
        return sql  # filter in python for simplicity

    trades = [dict(r) for r in await db.fetchall("SELECT * FROM positions WHERE night=? AND status='closed'", (night,))]
    red, green = [], []
    for t in trades:
        rec = {
            "name": t["name"] or t["symbol"] or t["mint"],
            "mint": t["mint"],
            "link": coin_url(t["mint"], "solana"),
            "entry": t["entry_price"],
            "exit": t["exit_price"],
            "pnl": t["pnl_usd"],
            "pct": t["pct"],
            "reason": t["exit_reason"],
            "fees": t["fees_usd"],
        }
        (green if (t["pnl_usd"] or 0) >= 0 and t["exit_reason"] != "stop" else red).append(rec)
        if t["exit_reason"] == "stop":
            if rec not in red:
                pass

    # stop trades always in red list
    red = [t for t in (red + green) if (t["pnl"] or 0) < 0 or t["reason"] == "stop"]
    green = [t for t in (red + green) if t not in red and (t["pnl"] or 0) >= 0]
    # rebuild cleanly
    red, green = [], []
    for t in trades:
        rec = {
            "name": t["name"] or t["symbol"] or t["mint"],
            "mint": t["mint"],
            "link": coin_url(t["mint"], "solana"),
            "entry": t["entry_price"],
            "exit": t["exit_price"],
            "pnl": t["pnl_usd"],
            "pct": t["pct"],
            "reason": t["exit_reason"],
            "fees": t["fees_usd"],
        }
        if (t["pnl_usd"] or 0) < 0 or t["exit_reason"] == "stop":
            red.append(rec)
        else:
            green.append(rec)

    coins = [dict(r) for r in await db.fetchall("SELECT * FROM coins WHERE night=?", (night,))]
    kills = [dict(r) for r in await db.fetchall(
        "SELECT reason, payload, mint, ts FROM scans WHERE verdict='kill' AND json_extract(payload,'$.ts') IS NOT NULL"
    )]
    # filter kills to tonight's coins if possible
    night_mints = {c["mint"] for c in coins}
    kills = [k for k in kills if k["mint"] in night_mints] or [dict(r) for r in await db.fetchall(
        "SELECT s.reason, s.payload, s.mint, s.ts FROM scans s JOIN coins c ON c.mint=s.mint WHERE s.verdict='kill' AND c.night=?",
        (night,),
    )]
    kill_reasons = Counter(k["reason"] or "?" for k in kills)

    audits = [dict(r) for r in await db.fetchall(
        "SELECT a.* FROM audits a JOIN coins c ON c.mint=a.mint WHERE a.passed=0 AND c.night=?",
        (night,),
    )]
    by_layer = []
    for a in audits:
        layers = json.loads(a["layers"] or "[]")
        redl = next((L for L in layers if L.get("pass") is False), None)
        by_layer.append({
            "mint": a["mint"], "link": coin_url(a["mint"], "solana"),
            "layer": (redl or {}).get("n"), "name": (redl or {}).get("name"),
            "value": a["reason"], "ts": a["ts"],
        })

    analyses = [dict(r) for r in await db.fetchall(
        "SELECT an.* FROM analyses an JOIN coins c ON c.mint=an.mint WHERE an.passed=0 AND c.night=?",
        (night,),
    )]
    anal_rows = [{
        "mint": a["mint"], "link": coin_url(a["mint"], "solana"),
        "failed": a["failed"], "score": a["score"],
    } for a in analyses]

    jev_tokens = 0
    jev_cost = 0
    fees_paid = sum(float(t["fees"] or 0) for t in red + green)

    out_dir = ROOT / "logs" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    day = night
    payload = {
        "night": night,
        "red": red,
        "green": green,
        "coins_seen": [{"mint": c["mint"], "name": c["name"], "symbol": c["symbol"], "link": coin_url(c["mint"], "solana")} for c in coins],
        "scanner_kills": dict(kill_reasons),
        "auditor_refusals": by_layer,
        "analyst_rejects": anal_rows,
        "jev_tokens": jev_tokens,
        "jev_cost": jev_cost,
        "fees_paid": fees_paid,
        "footer": "New to FOMO? " + SIGNUP_URL,
        "signup_url": SIGNUP_URL,
    }
    (out_dir / f"{day}.json").write_text(json.dumps(payload, indent=2) + "\n")

    def trade_md(t):
        return f"- {link(t['mint'], t['name'])}  entry {t['entry']} → {t['exit']}  {t['pnl']} ({t['pct']}%)  {t['reason']}"

    md = []
    md.append(f"# Desk night {day}")
    md.append("")
    md.append("## Red trades")
    md.extend(trade_md(t) for t in red) if red else md.append("- none")
    md.append("")
    md.append("## Green trades")
    md.extend(trade_md(t) for t in green) if green else md.append("- none")
    md.append("")
    md.append("## Coins seen")
    if coins:
        md.extend(f"- {link(c['mint'], c['name'] or c['symbol'] or c['mint'])}" for c in coins)
    else:
        md.append("- none")
    md.append("")
    md.append("## Scanner kills")
    if kill_reasons:
        md.extend(f"- {r}: {n}" for r, n in kill_reasons.items())
    else:
        md.append("- none")
    md.append("")
    md.append("## Auditor refusals")
    if by_layer:
        md.extend(f"- {link(a['mint'])}  layer {a['layer']} {a['name']}  {a['value']}  {a['ts']}" for a in by_layer)
    else:
        md.append("- none")
    md.append("")
    md.append("## Analyst rejects")
    if anal_rows:
        md.extend(f"- {link(a['mint'])}  Analyst (rules) · {a['failed']}" for a in anal_rows)
    else:
        md.append("- none")
    md.append("")
    md.append(f"Jev tokens used: {jev_tokens} (cost {jev_cost}) — rules mode, no Jev.")
    md.append(f"Fees paid: ${fees_paid:.4f}")
    md.append("")
    md.append("New to FOMO? " + SIGNUP_URL)
    md_path = out_dir / f"{day}.md"
    md_path.write_text("\n".join(md) + "\n")

    await db.set_kv("last_report_path", str(md_path))
    await db.set_kv("last_report_url", None)  # filled in once a Page exists
    await db.execute("UPDATE night_meta SET paper_complete=1, report_path=? WHERE night=?", (str(md_path), night))
    await db.clear_skips(night)

    tg = Telegram()
    if tg.ok:
        await tg.send(paper(f"Night report ready: {md_path}"))
        await tg.close()
    await db.close()
    print(md_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
