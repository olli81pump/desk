"""Publish the app + state.json to the `pages` branch (single force-pushed commit)."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("publisher")
ROOT = Path(__file__).resolve().parent
DOCS = ROOT / "docs"
SECRET = ROOT / ".secrets" / "DATA_PATH"
PAGES_BRANCH = "pages"
REMOTE = "origin"


def data_path() -> str:
    token = SECRET.read_text().strip()
    if len(token) < 32:
        raise RuntimeError("DATA_PATH missing or too short")
    return token


def data_dir() -> Path:
    d = DOCS / "d" / data_path()
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_state(state: dict) -> Path:
    out = data_dir() / "state.json"
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, separators=(",", ":"), ensure_ascii=False) + "\n")
    tmp.replace(out)
    return out


def _run(cmd: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)


def publish() -> bool:
    """Copy docs/ (app + current data) to an orphan commit on `pages` and force-push.

    Main history stays clean. The public Pages site is always exactly one commit.
    """
    if not SECRET.exists():
        log.error("no DATA_PATH secret; skip publish")
        return False
    if not (DOCS / "index.html").exists():
        log.error("docs/index.html missing")
        return False

    # Ensure we don't leak obvious secret files into the published tree
    with tempfile.TemporaryDirectory(prefix="desk-pages-") as td:
        dest = Path(td) / "site"
        shutil.copytree(
            DOCS,
            dest,
            ignore=shutil.ignore_patterns(".git", ".secrets", "*.pem", ".env*", "_screenshot"),
        )
        # no directory listing at /d/
        droot = dest / "d"
        droot.mkdir(exist_ok=True)
        if (droot / "index.html").exists():
            (droot / "index.html").unlink()
        _run(["git", "init", "-b", PAGES_BRANCH], dest)
        _run(["git", "config", "user.name", "olli81pump"], dest)
        _run(["git", "config", "user.email", "356546448+olli81pump@users.noreply.github.com"], dest)
        _run(["git", "add", "-A"], dest)
        msg = f"data {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}"
        _run(["git", "commit", "-m", msg, "--allow-empty"], dest)
        # remote from the source repo
        try:
            remote = _run(["git", "remote", "get-url", REMOTE], ROOT).stdout.strip()
        except subprocess.CalledProcessError:
            log.error("no git remote")
            return False
        _run(["git", "remote", "add", "origin", remote], dest)
        env = os.environ.copy()
        env["GIT_TERMINAL_PROMPT"] = "0"
        r = subprocess.run(
            ["git", "push", "--force", "origin", f"{PAGES_BRANCH}:{PAGES_BRANCH}"],
            cwd=dest,
            capture_output=True,
            text=True,
            env=env,
        )
        if r.returncode != 0:
            log.error("force-push pages failed: %s %s", r.stdout, r.stderr)
            return False
        log.info("published pages branch")
        return True
