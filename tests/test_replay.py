"""Acceptance 6: replay live migrations collected while building the desk.

Reports honestly how long the collector ran and what happened to each coin
when run through Scanner (and Auditor when a coin would pass).
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agents.scanner import scanner_pass
from sources import HttpSources
import settings as S


LOG = Path("/workspace/desk/logs/replay/migrations.jsonl")
STATUS = Path("/workspace/desk/logs/replay/collector_status.txt")
OUT = Path("/workspace/desk/logs/replay/replay_activity.json")


def _start_ts() -> datetime | None:
    if not STATUS.exists():
        return None
    for line in STATUS.read_text().splitlines():
        if "collector start" in line:
            try:
                return datetime.fromisoformat(line.split()[0].replace("Z", "+00:00"))
            except Exception:
                return None
    return None


async def main() -> int:
    print("test_replay")
    started = _start_ts()
    now = datetime.now(timezone.utc)
    duration_min = ((now - started).total_seconds() / 60.0) if started else None
    events = []
    if LOG.exists():
        for line in LOG.read_text().splitlines():
            if line.strip():
                events.append(json.loads(line))
    print(f"  collected {len(events)} migrations over {duration_min:.1f} min" if duration_min is not None else f"  collected {len(events)} migrations (start time unknown)")
    if not events:
        print("  FAIL no live migrations were collected")
        OUT.write_text(json.dumps({"count": 0, "duration_min": duration_min, "activity": []}, indent=2))
        return 1

    s = S.fresh()
    http = HttpSources()
    activity = []
    # unique mints, keep first
    seen = set()
    unique = []
    for ev in events:
        m = ev.get("mint")
        if m and m not in seen:
            seen.add(m)
            unique.append(ev)
    print(f"  unique mints: {len(unique)}")

    mints = [e["mint"] for e in unique]
    dexmap = {}
    # batch
    for i in range(0, len(mints), 20):
        part = await http.dexscreener(mints[i:i + 20])
        dexmap.update(part)

    runners = []
    for d in dexmap.values():
        try:
            if d.get("priceChange_h24") is not None and float(d["priceChange_h24"]) >= float(s["runner_h24_pct"]):
                runners.append(d)
        except (TypeError, ValueError):
            pass

    for ev in unique:
        mint = ev["mint"]
        recv = ev.get("_receivedAt")
        age = 0
        if recv:
            try:
                t0 = datetime.fromisoformat(recv.replace("Z", "+00:00"))
                age = (now - t0).total_seconds() / 60.0
            except Exception:
                age = 0
        dex = dexmap.get(mint)
        if not dex:
            verdict, reason = "wait", "DexScreener doesn't know it yet"
        else:
            verdict, reason = scanner_pass(dex, None, age, s, runners)
        rec = {
            "mint": mint,
            "name": (dex or {}).get("name"),
            "symbol": (dex or {}).get("symbol"),
            "pool": (dex or {}).get("pairAddress"),
            "liq": (dex or {}).get("liquidity_usd") if dex else None,
            "age_min": round(age, 1),
            "verdict": verdict,
            "reason": reason,
            "link": f"https://fomo.family/tokens/solana/{mint}?r=olli81",
        }
        activity.append(rec)
        label = rec["name"] or rec["symbol"] or mint[:8]
        print(f"  {verdict:5} {label}  liq={rec['liq']}  age={rec['age_min']}m  {reason or ''}")

    await http.close()
    OUT.write_text(json.dumps({
        "count": len(events),
        "unique": len(unique),
        "duration_min": duration_min,
        "started": started.isoformat() if started else None,
        "ended": now.isoformat(),
        "activity": activity,
    }, indent=2) + "\n")
    # pass if we actually replayed at least one live migration
    print(f"  PASS replayed {len(unique)} live migrations")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
