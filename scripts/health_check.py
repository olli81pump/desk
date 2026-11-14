#!/usr/bin/env python3
"""Hourly desk-health check. Restart if a heartbeat is older than 2 minutes.
Tell the owner via Telegram. Also warn if there were >10 websocket reconnects in the last hour.

This script is meant to be run by a Grok Bot routine (hourly). It cannot create that routine itself.
"""
from __future__ import annotations

import asyncio
import os
import signal
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from db import DB
from notify import Telegram, paper


AGENTS = ("scanner", "auditor", "analyst", "executor", "risk", "telegram", "publisher")


def parse_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


async def main() -> int:
    db = await DB().open()
    tg = Telegram()
    now = datetime.now(timezone.utc)
    hb = await db.heartbeats()
    restarted = []
    for agent in AGENTS:
        ts = parse_ts(hb.get(agent))
        if ts is None or now - ts > timedelta(minutes=2):
            down = 0 if ts is None else int((now - ts).total_seconds() // 60)
            restarted.append((agent, down))
    # process itself
    pid_file = ROOT / "logs" / "desk.pid"
    wrap = ROOT / "logs" / "wrapper.pid"
    alive = False
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
            os.kill(pid, 0)
            alive = True
        except Exception:
            alive = False
    if not alive or restarted:
        # If the wrapper is running it will restart the process after we kill it.
        if pid_file.exists():
            try:
                os.kill(int(pid_file.read_text().strip()), signal.SIGTERM)
            except Exception:
                pass
        if not wrap.exists():
            # start the wrapper in the background
            import subprocess
            log = ROOT / "logs"
            log.mkdir(exist_ok=True)
            subprocess.Popen(
                ["nohup", str(ROOT / "scripts" / "run_desk.sh")],
                cwd=ROOT,
                stdout=open(log / "wrapper.nohup", "a"),
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        for agent, down in restarted or [("desk", 0)]:
            await tg.send(paper(f"Restarted {agent}, down {down} min"))
    hour_ago = (now - timedelta(hours=1)).isoformat()
    n = await db.ws_reconnects_since(hour_ago)
    if n > 10:
        await tg.send(paper(f"PumpPortal websocket reconnected {n} times in the last hour"))
    await db.close()
    await tg.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
