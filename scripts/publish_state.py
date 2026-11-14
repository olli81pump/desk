#!/usr/bin/env python3
"""Write docs/d/{DATA_PATH}/state.json. DATA_PATH is read from .secrets only."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECRET = ROOT / ".secrets" / "DATA_PATH"


def data_dir() -> Path:
    if not SECRET.exists():
        sys.exit("missing .secrets/DATA_PATH")
    token = SECRET.read_text().strip()
    if len(token) < 32:
        sys.exit("DATA_PATH too short")
    d = ROOT / "docs" / "d" / token
    d.mkdir(parents=True, exist_ok=True)
    return d


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--nonce", default=None)
    p.add_argument("--note", default="step3")
    args = p.parse_args()
    payload = {
        "mode": "PAPER",
        "ok": True,
        "note": args.note,
        "nonce": args.nonce or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"),
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    out = data_dir() / "state.json"
    out.write_text(json.dumps(payload, indent=2) + "\n")
    print("wrote state.json nonce=" + payload["nonce"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
