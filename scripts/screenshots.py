#!/usr/bin/env python3
"""390px screenshots of Home, Agents, Auditor, Coin, Account + empty and error states."""
from __future__ import annotations

import json
import http.server
import socketserver
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
OUT = ROOT / "screens"
OUT.mkdir(parents=True, exist_ok=True)

# A rich fixture so Coin / Auditor / Agents have something to show
FIXTURE = {
    "mode": "PAPER",
    "ts": "2026-11-14T08:00:00+00:00",
    "balance": 214.55,
    "stack": 214.55,
    "fomo_handle": "olli81",
    "signup_url": "https://fomo.family/r/olli81",
    "profile_url": "https://fomo.family/profile/olli81?r=olli81",
    "notifier": "telegram",
    "notifier_note": "Web-Push ist in Plan B nicht verfügbar. Meldungen kommen über Telegram.",
    "settings": {
        "mode": "PAPER", "stop_pct": 6, "trail_pct": 12, "trail_start_pct": 20,
        "stack_pct": 8, "min_ticket_usd": 47.5, "analyst_mode": "rules",
        "fomo_handle": "olli81", "notifier": "telegram", "rpc_url": "https://api.mainnet-beta.solana.com",
    },
    "ticket_warning": "tickets bumped to $47.50 = 23.75% of stack",
    "positions": [{
        "mint": "DemoMint11111111111111111111111111111111111",
        "name": "Demo Cat", "symbol": "DCAT", "status": "open", "mode": "PAPER",
        "entry_price": 0.0012, "peak_price": 0.0015, "size_usd": 47.5,
        "stop_pct": 6, "trail_active": True,
        "link": "https://fomo.family/tokens/solana/DemoMint11111111111111111111111111111111111?r=olli81",
    }],
    "activity": [
        {"ts": "2026-11-14T07:00:00+00:00", "kind": "stopped", "mint": "X", "title": "Stopped Old",
         "agent": "Risk", "detail": "Risk · -6% stop", "right": "-$3.20 / -6.10%",
         "link": "https://fomo.family/tokens/solana/OldMint?r=olli81", "tone": "bad"},
        {"ts": "2026-11-14T07:10:00+00:00", "kind": "bought", "mint": "DemoMint11111111111111111111111111111111111",
         "title": "Bought Demo Cat", "agent": "Executor", "detail": "08:10",
         "right": "$47.50 · 23.75% of stack",
         "link": "https://fomo.family/tokens/solana/DemoMint11111111111111111111111111111111111?r=olli81", "tone": "buy"},
        {"ts": "2026-11-14T06:50:00+00:00", "kind": "kill", "mint": "Thin", "title": "ThinLiq",
         "agent": "Scanner", "detail": "liq $12.0K", "right": "liq $12.0K",
         "link": "https://fomo.family/tokens/solana/Thin?r=olli81", "tone": "kill"},
    ],
    "waiting": [],
    "latest_audit": {
        "mint": "DemoMint11111111111111111111111111111111111",
        "name": "Demo Cat", "passed": True, "reason": None, "holders": 1200,
        "link": "https://fomo.family/tokens/solana/DemoMint11111111111111111111111111111111111?r=olli81",
        "layers": [
            {"n": 1, "name": "Mint authority", "pass": True, "value": "Revoked"},
            {"n": 2, "name": "Freeze authority", "pass": True, "value": "Revoked"},
            {"n": 3, "name": "Dev wallet", "pass": True, "value": "0.9% · sold 0"},
            {"n": 4, "name": "Top 10 holders", "pass": True, "value": "16.8%"},
            {"n": 5, "name": "Liquidity", "pass": True, "value": "99.98% locked"},
            {"n": 6, "name": "Pool age", "pass": True, "value": "43m"},
            {"n": 7, "name": "Bundled wallets", "pass": True, "value": "None"},
            {"n": 8, "name": "Delegations", "pass": True, "value": "None"},
        ],
    },
    "agents": {
        "scanner": {"name": "Scanner", "card": "3 pools", "sub": "2 passed · 4 killed", "feed": [
            {"mint": "DemoMint11111111111111111111111111111111111", "name": "Demo Cat", "verdict": "pass",
             "liq": 52000, "link": "https://fomo.family/tokens/solana/DemoMint11111111111111111111111111111111111?r=olli81"},
            {"mint": "Thin", "name": "ThinLiq", "verdict": "kill", "reason": "liq $12.0K",
             "link": "https://fomo.family/tokens/solana/Thin?r=olli81"},
        ]},
        "auditor": {"name": "Auditor", "card": "2 taken apart", "sub": "0 rejected"},
        "analyst": {"name": "Analyst", "card": "Scoring", "sub": "mode rules · 1 scored", "min_score": 70,
                    "last": {"score": 78, "passed": True, "model": "rules"}},
        "executor": {"name": "Executor", "card": "1 trades", "sub": "8% of stack"},
        "risk": {"name": "Risk", "card": "Guarding", "sub": "Stopped",
                 "pills": {"stop": "stop -6%", "trail": "trail 12%"}},
    },
    "coins": {},
}

prices = [{"ts": f"2026-11-14T07:{i:02d}:00Z", "price": 0.0012 + i * 0.00001, "v": 100} for i in range(40)]
FIXTURE["coins"] = {
    "DemoMint11111111111111111111111111111111111": {
        "mint": "DemoMint11111111111111111111111111111111111",
        "name": "Demo Cat", "symbol": "DCAT", "status": "open",
        "link": "https://fomo.family/tokens/solana/DemoMint11111111111111111111111111111111111?r=olli81",
        "prices": prices,
        "audit": FIXTURE["latest_audit"],
        "position": FIXTURE["positions"][0],
        "stop_pct": 6,
    }
}


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(DOCS), **k)

    def log_message(self, *a):
        pass


def serve():
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", 8798), Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd


def main() -> int:
    # write fixture next to the app; screenshots use ?fixture= or a saved file served at a fake path
    # Easier: inject by writing a local fixture state and using query fixture= for empty/error,
    # and for populated screens use localStorage + a temporary data dir? 
    # The app loads d/{DATA_PATH}/state.json. For screenshots we use a known fake path
    # 'fixturepath_for_screenshots_only________xx' written only under /tmp? 
    # Simpler: add screenshot mode via query `?fixture=demo` in app.js — I didn't add demo.
    # I'll write the fixture into docs/d/_screenshot/state.json (name is not the real DATA_PATH)
    # and open #d=_screenshot
    dest = DOCS / "d" / "_screenshot"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "state.json").write_text(json.dumps(FIXTURE) + "\n")

    httpd = serve()
    from playwright.sync_api import sync_playwright

    shots = [
        ("home", "/#d=_screenshot&/home"),
        ("agents", "/#d=_screenshot&/agents"),
        ("auditor", "/#d=_screenshot&/auditor"),
        ("coin", "/#d=_screenshot&/coin/DemoMint11111111111111111111111111111111111"),
        ("account", "/#d=_screenshot&/account"),
        ("home_empty", "/?fixture=empty#/home"),
        ("agents_empty", "/?fixture=empty#/agents"),
        ("auditor_empty", "/?fixture=empty#/auditor"),
        ("coin_empty", "/?fixture=empty#/coin/UnknownMint"),
        ("account_empty", "/?fixture=empty#/account"),
        ("home_error", "/?fixture=error#/home"),
        ("agents_error", "/?fixture=error#/agents"),
        ("auditor_error", "/?fixture=error#/auditor"),
        ("coin_error", "/?fixture=error#/coin/x"),
        ("account_error", "/?fixture=error#/account"),
    ]
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", args=["--no-sandbox"])
        long = {"agents", "account", "agents_empty", "account_empty"}
        for name, path in shots:
            h = 1400 if name in long else 844
            page = browser.new_page(viewport={"width": 390, "height": h}, device_scale_factor=2)
            url = "http://127.0.0.1:8798" + path
            page.goto(url, wait_until="networkidle")
            page.wait_for_timeout(400)
            out = OUT / f"{name}.png"
            page.screenshot(path=str(out), full_page=False)
            print("wrote", out)
            page.close()
        browser.close()
    httpd.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
