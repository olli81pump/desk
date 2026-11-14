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

import sys
sys.path.insert(0, str(ROOT))
from links import SIGNUP_URL, coin_url, profile_url

DEMO_MINT = "DemoMint11111111111111111111111111111111111"
DEMO_LINK = coin_url(DEMO_MINT, "solana")
THIN_LINK = coin_url("Thin", "solana")

# A rich fixture so Coin / Auditor / Agents have something to show
FIXTURE = {
    "mode": "PAPER",
    "ts": "2026-11-14T08:00:00+00:00",
    "balance": 52.40,
    "stack": 52.40,
    "fomo_handle": "olli81",
    "signup_url": SIGNUP_URL,
    "profile_url": profile_url("olli81"),
    "notifier": "telegram",
    "notifier_note": "Web-Push ist in Plan B nicht verfügbar. Meldungen kommen über Telegram.",
    "settings": {
        "mode": "PAPER", "stop_pct": 6, "trail_pct": 12, "trail_start_pct": 20,
        "stack_pct": 8, "min_ticket_usd": 5, "min_size_usd": 5, "max_size_usd": 10,
        "max_pool_pct": 2, "tp1_pct": 50, "tp1_fraction": 0.333, "tp2_pct": 100, "tp2_fraction": 0.333,
        "analyst_mode": "rules",
        "fomo_handle": "olli81", "notifier": "telegram", "rpc_url": "https://api.mainnet-beta.solana.com",
    },
    "ticket_warning": None,
    "positions": [{
        "mint": "DemoMint11111111111111111111111111111111111",
        "name": "Demo Cat", "symbol": "DCAT", "status": "open", "mode": "PAPER",
        "entry_price": 0.0012, "peak_price": 0.00186, "size_usd": 6.67,
        "original_size_usd": 10, "realized_pnl_usd": 1.55,
        "stop_pct": 6, "trail_active": True,
        "tp1_hit": True, "tp2_hit": False, "tp1_pct": 50, "tp2_pct": 100,
        "tp1_fraction": 0.333, "tp2_fraction": 0.333,
        "link": DEMO_LINK,
    }],
    "activity": [
        {"ts": "2026-11-14T07:00:00+00:00", "kind": "took_profit", "mint": "DemoMint11111111111111111111111111111111111",
         "title": "Took profit Demo Cat",
         "agent": "Risk", "detail": "+50% · 1/3", "right": "+$1.55",
         "link": DEMO_LINK, "tone": "good"},
        {"ts": "2026-11-14T07:10:00+00:00", "kind": "bought", "mint": "DemoMint11111111111111111111111111111111111",
         "title": "Bought Demo Cat", "agent": "Executor", "detail": "08:10",
         "right": "$10.00 · 20.00% of stack",
         "link": DEMO_LINK, "tone": "buy"},
        {"ts": "2026-11-14T07:09:00+00:00", "kind": "sized", "mint": "DemoMint11111111111111111111111111111111111",
         "title": "Sized Demo Cat", "agent": "Brain", "detail": "score 100",
         "right": "$10.00 · 20.00% of stack",
         "link": DEMO_LINK, "tone": "pass"},
        {"ts": "2026-11-14T06:50:00+00:00", "kind": "kill", "mint": "Thin", "title": "ThinLiq",
         "agent": "Scanner", "detail": "liq $12.0K", "right": "liq $12.0K",
         "link": THIN_LINK, "tone": "kill"},
    ],
    "waiting": [],
    "latest_audit": {
        "mint": "DemoMint11111111111111111111111111111111111",
        "name": "Demo Cat", "passed": True, "reason": None, "holders": 1200,
        "link": DEMO_LINK,
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
             "liq": 52000, "link": DEMO_LINK},
            {"mint": "Thin", "name": "ThinLiq", "verdict": "kill", "reason": "liq $12.0K",
             "link": THIN_LINK},
        ]},
        "auditor": {"name": "Auditor", "card": "2 taken apart", "sub": "0 rejected"},
        "analyst": {"name": "Analyst", "card": "Scoring", "sub": "mode rules · 1 scored", "min_score": 70,
                    "last": {"score": 78, "passed": True, "model": "rules"}},
        "brain": {"name": "Brain", "card": "1 sized", "sub": "$5–$10",
                  "decisions": [
                      {"mint": "DemoMint11111111111111111111111111111111111", "name": "Demo Cat", "score": 100,
                       "sizeUsd": 10, "stackPct": 20, "skipped": False,
                       "link": DEMO_LINK}
                  ]},
        "executor": {"name": "Executor", "card": "1 trades", "sub": "Brain sizes"},
        "risk": {"name": "Risk", "card": "Guarding", "sub": "Took profit",
                 "pills": {"stop": "stop -6%", "trail": "trail 12%", "tp": "TP 50%/100%"}},
    },
    "coins": {},
}

prices = [{"ts": f"2026-11-14T07:{i:02d}:00Z", "price": 0.0012 + i * 0.00001, "v": 100} for i in range(40)]
FIXTURE["coins"] = {
    "DemoMint11111111111111111111111111111111111": {
        "mint": "DemoMint11111111111111111111111111111111111",
        "name": "Demo Cat", "symbol": "DCAT", "status": "open",
        "link": DEMO_LINK,
        "prices": prices,
        "audit": FIXTURE["latest_audit"],
        "position": FIXTURE["positions"][0],
        "stop_pct": 6,
    }
}
FIXTURE["positions"][0]["prices"] = prices


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
