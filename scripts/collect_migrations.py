#!/usr/bin/env python3
"""Collect live PumpPortal migration events while the desk is being built."""
import asyncio, json, time
from datetime import datetime, timezone
from pathlib import Path

OUT = Path("/workspace/desk/logs/replay/migrations.jsonl")
STATUS = Path("/workspace/desk/logs/replay/collector_status.txt")
URL = "wss://pumpportal.fun/api/data"
OUT.parent.mkdir(parents=True, exist_ok=True)

def log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}\n"
    with STATUS.open("a") as f:
        f.write(line)

def is_migration(parsed) -> bool:
    if not isinstance(parsed, dict):
        return False
    if set(parsed.keys()) <= {"message", "errors", "error"} and "mint" not in parsed:
        return False
    return True

async def main() -> None:
    import websockets
    log("collector start")
    backoff = 1
    n = 0
    while True:
        try:
            async with websockets.connect(URL, open_timeout=20, ping_interval=20, ping_timeout=20) as ws:
                await ws.send(json.dumps({"method": "subscribeMigration"}))
                log("subscribed")
                backoff = 1
                last = time.time()
                while True:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=30)
                    except asyncio.TimeoutError:
                        if time.time() - last > 120:
                            log("silent 120s, reconnect")
                            break
                        continue
                    last = time.time()
                    try:
                        parsed = json.loads(raw)
                    except Exception:
                        continue
                    if not is_migration(parsed):
                        continue
                    parsed["_receivedAt"] = datetime.now(timezone.utc).isoformat()
                    with OUT.open("a") as f:
                        f.write(json.dumps(parsed, separators=(",", ":")) + "\n")
                    n += 1
                    mint = parsed.get("mint", "?")
                    log(f"saved #{n} mint={mint[:8]}…")
        except Exception as e:
            log(f"ws error {type(e).__name__}: {e}; retry {backoff}s")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)

if __name__ == "__main__":
    asyncio.run(main())
