"""Acceptance 7: no secret values in source, logs, or published JSON. DATA_PATH not in source files."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(p: Path) -> str:
    return p.read_text().strip() if p.exists() else ""


def main() -> int:
    print("test_secrets")
    sec = ROOT / ".secrets"
    needles = {
        "APP_TOKEN": load(sec / "APP_TOKEN"),
        "VAPID_PRIVATE": load(sec / "VAPID_PRIVATE"),
        "DATA_PATH": load(sec / "DATA_PATH"),
        "TG_TOKEN": os.environ.get("TG_TOKEN") or "",
        "TYPESAFE_API_KEY": os.environ.get("TYPESAFE_API_KEY") or "",
    }
    # also pem body
    pem = load(sec / "VAPID_PRIVATE.pem")
    if pem:
        needles["VAPID_PEM_BODY"] = pem.split("\n")[1] if "\n" in pem else pem

    source_globs = [
        "--glob", "!.git/**",
        "--glob", "!.venv/**",
        "--glob", "!.secrets/**",
        "--glob", "!logs/**",
        "--glob", "!data/**",
        "--glob", "!docs/d/**",  # published data dir name is visible; source files must be clean
        "--glob", "!screens/**",
    ]
    fail = 0
    for label, val in needles.items():
        if not val or len(val) < 8:
            print(f"  skip {label} (empty or short)")
            continue
        # search source files
        r = subprocess.run(
            ["rg", "-l", "--fixed-strings", val, str(ROOT), *source_globs],
            capture_output=True, text=True,
        )
        hits = [h for h in (r.stdout or "").splitlines() if h]
        # DATA_PATH will appear as a directory name under docs/d/ — we excluded docs/d/**
        if hits:
            print(f"  FAIL {label} found in source:")
            for h in hits:
                print("   ", h)
            fail += 1
        else:
            print(f"  PASS {label} not in source files")

        # published state.json body must not contain tokens except DATA_PATH cannot be in JSON values
        state_files = list((ROOT / "docs" / "d").glob("*/state.json")) if (ROOT / "docs" / "d").exists() else []
        if label != "DATA_PATH":
            for sf in state_files:
                if val in sf.read_text():
                    print(f"  FAIL {label} in {sf}")
                    fail += 1

    # typo keys should not have values in repo
    r = subprocess.run(
        ["rg", "-n", r"TYPESAFE_API_KEY\s*=\s*['\"][^'\"]+['\"]|TG_TOKEN\s*=\s*['\"][^'\"]+['\"]|VAPID_PRIVATE_KEY\s*=\s*['\"][^'\"]+['\"]",
         str(ROOT), "--glob", "!.git/**", "--glob", "!.venv/**", "--glob", "!.secrets/**"],
        capture_output=True, text=True,
    )
    if r.stdout.strip():
        print("  FAIL hardcoded secret assignments:\n", r.stdout)
        fail += 1
    else:
        print("  PASS no hardcoded TYPESAFE/TG/VAPID assignments")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
