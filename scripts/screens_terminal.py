#!/usr/bin/env python3
"""Screenshots of the terminal app using a real state.json (copied to the gitignored _screenshot path)."""
from __future__ import annotations

import http.server
import shutil
import socketserver
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
OUT = ROOT / "screens"


class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(DOCS), **k)

    def log_message(self, *a):
        pass


def main(src: str, prefix: str = "terminal") -> int:
    OUT.mkdir(exist_ok=True)
    dest = DOCS / "d" / "_screenshot"
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, dest / "state.json")
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", 8799), H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    from playwright.sync_api import sync_playwright
    shots = [("home", "/home", 844), ("stats", "/stats", 844), ("agents", "/agents", 844), ("account", "/account", 1400)]
    errs = []
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", args=["--no-sandbox"])
        for name, route, h in shots:
            pg = b.new_page(viewport={"width": 390, "height": h}, device_scale_factor=2)
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
            pg.goto(f"http://127.0.0.1:8799/#d=_screenshot&{route}", wait_until="networkidle")
            pg.wait_for_timeout(500)
            out = OUT / f"{prefix}_{name}.png"
            pg.screenshot(path=str(out), full_page=True)
            print("wrote", out)
            if name in ("stats", "agents"):
                full_h = pg.evaluate("document.documentElement.scrollHeight")
                y, i = 0, 1
                while y < full_h - 200:
                    pg.evaluate(f"window.scrollTo(0, {y})")
                    pg.wait_for_timeout(150)
                    part = OUT / f"{prefix}_{name}_{i}.png"
                    pg.screenshot(path=str(part))
                    print("wrote", part)
                    y += 640; i += 1
            pg.close()
        b.close()
    httpd.shutdown()
    print("js errors:", errs or "none")
    return 1 if errs else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], *(sys.argv[2:3])))
