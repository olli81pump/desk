"""SQLite store for the desk. Path is local and gitignored."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "desk.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (
  k TEXT PRIMARY KEY,
  v TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS coins (
  mint TEXT PRIMARY KEY,
  name TEXT,
  symbol TEXT,
  pool TEXT,
  creator TEXT,
  creator_balance_at_migration REAL,
  migrated_at TEXT,
  seen_at TEXT,
  night TEXT,
  status TEXT,
  coin_url TEXT
);
CREATE TABLE IF NOT EXISTS waiting (
  mint TEXT PRIMARY KEY,
  added_at TEXT,
  last_poll_at TEXT,
  passed INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS scans (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT,
  mint TEXT,
  verdict TEXT,
  reason TEXT,
  payload TEXT
);
CREATE TABLE IF NOT EXISTS audits (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT,
  mint TEXT,
  passed INTEGER,
  reason TEXT,
  layers TEXT,
  holders INTEGER,
  payload TEXT
);
CREATE TABLE IF NOT EXISTS analyses (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT,
  mint TEXT,
  passed INTEGER,
  score INTEGER,
  failed TEXT,
  payload TEXT
);
CREATE TABLE IF NOT EXISTS executions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT,
  mint TEXT,
  status TEXT,
  size_usd REAL,
  signal_price REAL,
  reason TEXT,
  payload TEXT
);
CREATE TABLE IF NOT EXISTS positions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  mint TEXT,
  name TEXT,
  symbol TEXT,
  status TEXT,
  mode TEXT,
  opened_at TEXT,
  closed_at TEXT,
  entry_price REAL,
  exit_price REAL,
  peak_price REAL,
  size_usd REAL,
  stop_pct REAL,
  trail_active INTEGER DEFAULT 0,
  exit_reason TEXT,
  pnl_usd REAL,
  fees_usd REAL,
  pct REAL,
  link TEXT,
  night TEXT,
  original_size_usd REAL,
  realized_pnl_usd REAL DEFAULT 0,
  tp1_hit INTEGER DEFAULT 0,
  tp2_hit INTEGER DEFAULT 0,
  tp1_price REAL,
  tp2_price REAL,
  fees_realized_usd REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS brains (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT,
  mint TEXT,
  score REAL,
  size_usd REAL,
  stack_pct REAL,
  cap_hit TEXT,
  reason TEXT,
  skipped INTEGER,
  payload TEXT,
  night TEXT
);
CREATE TABLE IF NOT EXISTS activity (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT,
  kind TEXT,
  mint TEXT,
  title TEXT,
  agent TEXT,
  detail TEXT,
  right TEXT,
  link TEXT,
  tone TEXT,
  night TEXT
);
CREATE TABLE IF NOT EXISTS prices (
  mint TEXT,
  ts TEXT,
  price REAL,
  volume_m5 REAL
);
CREATE INDEX IF NOT EXISTS idx_prices_mint_ts ON prices(mint, ts);
CREATE TABLE IF NOT EXISTS skips (
  mint TEXT,
  ts TEXT,
  reason TEXT,
  night TEXT
);
CREATE TABLE IF NOT EXISTS heartbeats (
  agent TEXT PRIMARY KEY,
  ts TEXT,
  extra TEXT
);
CREATE TABLE IF NOT EXISTS ws_reconnects (
  ts TEXT
);
CREATE TABLE IF NOT EXISTS night_meta (
  night TEXT PRIMARY KEY,
  started_at TEXT,
  paper_complete INTEGER DEFAULT 0,
  report_path TEXT
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def current_night(report_time: str = "08:00") -> str:
    """A 'night' is the window from today's report_time to the next (Europe/Berlin)."""
    from zoneinfo import ZoneInfo
    tz = ZoneInfo("Europe/Berlin")
    now = datetime.now(tz)
    hh, mm = (int(x) for x in report_time.split(":")[:2])
    boundary = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    start = boundary if now >= boundary else boundary.replace(day=now.day) 
    if now < boundary:
        from datetime import timedelta
        start = boundary - timedelta(days=1)
    else:
        start = boundary
    return start.strftime("%Y-%m-%d")


class DB:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path or DB_PATH)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._c: aiosqlite.Connection | None = None

    async def open(self) -> "DB":
        self._c = await aiosqlite.connect(self.path)
        self._c.row_factory = aiosqlite.Row
        await self._c.executescript(SCHEMA)
        await self._c.commit()
        await self._migrate()
        return self

    async def _migrate(self) -> None:
        """Add columns/tables that CREATE TABLE IF NOT EXISTS will not add on an existing db."""
        await self.c.executescript(
            """
            CREATE TABLE IF NOT EXISTS brains (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              ts TEXT,
              mint TEXT,
              score REAL,
              size_usd REAL,
              stack_pct REAL,
              cap_hit TEXT,
              reason TEXT,
              skipped INTEGER,
              payload TEXT,
              night TEXT
            );
            """
        )
        cur = await self.c.execute("PRAGMA table_info(positions)")
        rows = await cur.fetchall()
        names = {r["name"] for r in rows}
        for col, typ in (
            ("original_size_usd", "REAL"),
            ("realized_pnl_usd", "REAL DEFAULT 0"),
            ("tp1_hit", "INTEGER DEFAULT 0"),
            ("tp2_hit", "INTEGER DEFAULT 0"),
            ("tp1_price", "REAL"),
            ("tp2_price", "REAL"),
            ("fees_realized_usd", "REAL DEFAULT 0"),
        ):
            if col not in names:
                await self.c.execute(f"ALTER TABLE positions ADD COLUMN {col} {typ}")
        await self.c.commit()

    async def close(self) -> None:
        if self._c:
            await self._c.close()
            self._c = None

    @property
    def c(self) -> aiosqlite.Connection:
        assert self._c is not None
        return self._c

    async def execute(self, sql: str, params: tuple = ()) -> None:
        await self.c.execute(sql, params)
        await self.c.commit()

    async def executemany(self, sql: str, seq) -> None:
        await self.c.executemany(sql, seq)
        await self.c.commit()

    async def fetchone(self, sql: str, params: tuple = ()):
        cur = await self.c.execute(sql, params)
        return await cur.fetchone()

    async def fetchall(self, sql: str, params: tuple = ()):
        cur = await self.c.execute(sql, params)
        return await cur.fetchall()

    async def get_kv(self, k: str, default=None):
        row = await self.fetchone("SELECT v FROM kv WHERE k=?", (k,))
        if not row:
            return default
        return json.loads(row["v"])

    async def set_kv(self, k: str, v: Any) -> None:
        await self.execute(
            "INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            (k, json.dumps(v)),
        )

    async def load_settings(self) -> dict:
        from settings import fresh
        s = fresh()
        stored = await self.get_kv("settings")
        if stored:
            s.update(stored)
        return s

    async def save_settings(self, s: dict) -> None:
        await self.set_kv("settings", s)

    async def heartbeat(self, agent: str, extra: dict | None = None) -> None:
        await self.execute(
            "INSERT INTO heartbeats(agent,ts,extra) VALUES(?,?,?) "
            "ON CONFLICT(agent) DO UPDATE SET ts=excluded.ts, extra=excluded.extra",
            (agent, _now(), json.dumps(extra or {})),
        )

    async def heartbeats(self) -> dict[str, str]:
        rows = await self.fetchall("SELECT agent, ts FROM heartbeats")
        return {r["agent"]: r["ts"] for r in rows}

    async def log_ws_reconnect(self) -> None:
        await self.execute("INSERT INTO ws_reconnects(ts) VALUES(?)", (_now(),))

    async def ws_reconnects_since(self, iso_from: str) -> int:
        row = await self.fetchone(
            "SELECT COUNT(*) n FROM ws_reconnects WHERE ts>=?", (iso_from,)
        )
        return int(row["n"] if row else 0)

    async def upsert_coin(self, **kw) -> None:
        mint = kw["mint"]
        existing = await self.fetchone("SELECT mint FROM coins WHERE mint=?", (mint,))
        if not existing:
            await self.execute(
                "INSERT INTO coins(mint,name,symbol,pool,creator,creator_balance_at_migration,"
                "migrated_at,seen_at,night,status,coin_url) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    mint,
                    kw.get("name"),
                    kw.get("symbol"),
                    kw.get("pool"),
                    kw.get("creator"),
                    kw.get("creator_balance_at_migration"),
                    kw.get("migrated_at"),
                    kw.get("seen_at") or _now(),
                    kw.get("night"),
                    kw.get("status") or "seen",
                    kw.get("coin_url"),
                ),
            )
            return
        fields = []
        vals = []
        for k in ("name", "symbol", "pool", "creator", "creator_balance_at_migration",
                  "migrated_at", "status", "coin_url", "night"):
            if k in kw and kw[k] is not None:
                fields.append(f"{k}=?")
                vals.append(kw[k])
        if fields:
            vals.append(mint)
            await self.execute(f"UPDATE coins SET {', '.join(fields)} WHERE mint=?", tuple(vals))

    async def coin(self, mint: str):
        return await self.fetchone("SELECT * FROM coins WHERE mint=?", (mint,))

    async def find_coins(self, q: str, night: str | None = None) -> list:
        ql = q.strip()
        if not ql:
            return []
        # exact mint
        row = await self.fetchone("SELECT * FROM coins WHERE mint=?", (ql,))
        if row:
            return [row]
        sql = "SELECT * FROM coins WHERE lower(name)=? OR lower(symbol)=? OR lower(name) LIKE ? OR lower(symbol) LIKE ?"
        params: list = [ql.lower(), ql.lower(), f"%{ql.lower()}%", f"%{ql.lower()}%"]
        if night:
            sql += " AND night=?"
            params.append(night)
        return list(await self.fetchall(sql, tuple(params)))

    async def add_price(self, mint: str, price: float, volume_m5: float | None, ts: str | None = None) -> None:
        await self.execute(
            "INSERT INTO prices(mint,ts,price,volume_m5) VALUES(?,?,?,?)",
            (mint, ts or _now(), price, volume_m5),
        )

    async def prices(self, mint: str, limit: int = 400) -> list:
        return list(await self.fetchall(
            "SELECT ts, price, volume_m5 FROM prices WHERE mint=? ORDER BY ts DESC LIMIT ?",
            (mint, limit),
        ))

    async def add_activity(self, **kw) -> None:
        await self.execute(
            "INSERT INTO activity(ts,kind,mint,title,agent,detail,right,link,tone,night) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                kw.get("ts") or _now(),
                kw.get("kind"),
                kw.get("mint"),
                kw.get("title"),
                kw.get("agent"),
                kw.get("detail"),
                kw.get("right"),
                kw.get("link"),
                kw.get("tone") or "neutral",
                kw.get("night"),
            ),
        )

    async def add_scan(self, payload: dict) -> None:
        await self.execute(
            "INSERT INTO scans(ts,mint,verdict,reason,payload) VALUES(?,?,?,?,?)",
            (payload.get("ts") or _now(), payload.get("mint"), payload.get("verdict"),
             payload.get("reason"), json.dumps(payload)),
        )

    async def add_audit(self, payload: dict) -> None:
        await self.execute(
            "INSERT INTO audits(ts,mint,passed,reason,layers,holders,payload) VALUES(?,?,?,?,?,?,?)",
            (
                payload.get("ts") or _now(),
                payload.get("mint"),
                1 if payload.get("passed") else 0,
                payload.get("reason"),
                json.dumps(payload.get("layers") or []),
                payload.get("holders"),
                json.dumps(payload),
            ),
        )

    async def latest_audit(self, mint: str):
        return await self.fetchone(
            "SELECT * FROM audits WHERE mint=? ORDER BY id DESC LIMIT 1", (mint,)
        )

    async def add_analysis(self, payload: dict) -> None:
        await self.execute(
            "INSERT INTO analyses(ts,mint,passed,score,failed,payload) VALUES(?,?,?,?,?,?)",
            (
                payload.get("ts") or _now(),
                payload.get("mint"),
                1 if payload.get("passed") else 0,
                payload.get("score"),
                json.dumps(payload.get("failed") or []),
                json.dumps(payload),
            ),
        )

    async def add_brain(self, payload: dict) -> None:
        await self.execute(
            "INSERT INTO brains(ts,mint,score,size_usd,stack_pct,cap_hit,reason,skipped,payload,night) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                payload.get("ts") or _now(),
                payload.get("mint"),
                payload.get("score"),
                payload.get("sizeUsd"),
                payload.get("stackPct"),
                payload.get("capHit"),
                payload.get("reason"),
                1 if payload.get("skipped") else 0,
                json.dumps(payload),
                payload.get("night"),
            ),
        )

    async def recent_brains(self, limit: int = 20) -> list:
        return list(await self.fetchall(
            "SELECT * FROM brains ORDER BY id DESC LIMIT ?", (limit,)
        ))

    async def add_execution(self, payload: dict) -> None:
        await self.execute(
            "INSERT INTO executions(ts,mint,status,size_usd,signal_price,reason,payload) "
            "VALUES(?,?,?,?,?,?,?)",
            (
                payload.get("ts") or _now(),
                payload.get("mint"),
                payload.get("status"),
                payload.get("sizeUsd"),
                payload.get("signalPrice"),
                payload.get("reason"),
                json.dumps(payload),
            ),
        )

    async def open_positions(self) -> list:
        return list(await self.fetchall(
            "SELECT * FROM positions WHERE status IN ('open','exiting') ORDER BY id"
        ))

    async def position_for_mint(self, mint: str):
        return await self.fetchone(
            "SELECT * FROM positions WHERE mint=? AND status IN ('open','exiting') ORDER BY id DESC LIMIT 1",
            (mint,),
        )

    async def add_skip(self, mint: str, reason: str, night: str) -> None:
        await self.execute(
            "INSERT INTO skips(mint,ts,reason,night) VALUES(?,?,?,?)",
            (mint, _now(), reason, night),
        )

    async def clear_skips(self, night: str | None = None) -> None:
        if night:
            await self.execute("DELETE FROM skips WHERE night=?", (night,))
        else:
            await self.execute("DELETE FROM skips")
