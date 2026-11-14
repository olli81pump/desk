"""Telegram notifier. Owner-only. Never prints the token."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import aiohttp

from links import coin_url

log = logging.getLogger("notify")
ROOT = Path(__file__).resolve().parent
SECRETS = ROOT / ".secrets"


def load_token() -> str | None:
    return os.environ.get("TG_TOKEN") or None


def load_owner_chat_id() -> str | None:
    p = SECRETS / "owner_chat_id"
    if p.exists():
        return p.read_text().strip() or None
    return None


def buy_keyboard(mint: str, chain: str = "solana") -> dict:
    return {
        "inline_keyboard": [
            [{"text": "Buy on FOMO", "url": coin_url(mint, chain)}],
        ]
    }


def sell_keyboard(mint: str, chain: str = "solana") -> dict:
    return {
        "inline_keyboard": [
            [{"text": "Sell on FOMO", "url": coin_url(mint, chain)}],
        ]
    }


MODE = "PAPER"  # set by desk on load / switch


def paper(text: str, mode: str | None = None) -> str:
    t = text.strip()
    if t.startswith("PAPER") or t.startswith("LIVE"):
        return t
    return ("LIVE · " if (mode or MODE) == "LIVE" else "PAPER · ") + t


class Telegram:
    def __init__(self, session: aiohttp.ClientSession | None = None):
        self.token = load_token()
        self.owner = load_owner_chat_id()
        self._session = session
        self._own = False
        self.offset = 0

    @property
    def ok(self) -> bool:
        return bool(self.token and self.owner)

    def _url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self.token}/{method}"

    async def _sess(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=40))
            self._own = True
        return self._session

    async def close(self) -> None:
        if self._own and self._session and not self._session.closed:
            await self._session.close()

    async def send_to(self, chat_id: str, text: str, keyboard: dict | None = None) -> bool:
        return await self.send(text, keyboard, retries=3, chat_id=chat_id)

    async def send(self, text: str, keyboard: dict | None = None, retries: int = 3, chat_id: str | None = None) -> bool:
        if not self.ok:
            log.warning("telegram not configured; drop message")
            return False
        sess = await self._sess()
        payload: dict[str, Any] = {
            "chat_id": chat_id or self.owner,
            "text": text,
            "disable_web_page_preview": True,
        }
        if keyboard:
            payload["reply_markup"] = keyboard
        last = None
        for i in range(retries):
            try:
                async with sess.post(self._url("sendMessage"), json=payload) as r:
                    data = await r.json()
                    if data.get("ok"):
                        return True
                    last = RuntimeError(str(data))
            except Exception as e:
                last = e
            await asyncio_sleep(1 + i)
        log.error("telegram send failed: %s", last)
        return False

    async def get_updates(self, timeout: int = 25) -> list[dict]:
        if not self.ok:
            return []
        sess = await self._sess()
        params = {"offset": self.offset, "timeout": timeout, "allowed_updates": ["message", "callback_query", "my_chat_member", "channel_post"]}
        try:
            async with sess.get(self._url("getUpdates"), params=params) as r:
                data = await r.json()
        except Exception as e:
            log.warning("getUpdates: %s", e)
            return []
        if not data.get("ok"):
            return []
        updates = data.get("result") or []
        for u in updates:
            self.offset = max(self.offset, int(u.get("update_id", 0)) + 1)
        return updates


async def asyncio_sleep(n: float) -> None:
    import asyncio
    await asyncio.sleep(n)


CHANNEL_FILE = SECRETS / "signal_channel_id"


def load_channel_id() -> str | None:
    if CHANNEL_FILE.exists():
        return CHANNEL_FILE.read_text().strip() or None
    return None


def save_channel_id(cid: str) -> None:
    CHANNEL_FILE.write_text(str(cid))
    try:
        CHANNEL_FILE.chmod(0o600)
    except OSError:
        pass
