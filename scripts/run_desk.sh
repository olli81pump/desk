#!/bin/bash
# Restart wrapper for the always-on PAPER desk.
set -u
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
# shellcheck disable=SC1091
. "$ROOT/.venv/bin/activate"
export PYTHONPATH="$ROOT"
export PYTHONUNBUFFERED=1
mkdir -p "$ROOT/logs"
echo $$ > "$ROOT/logs/wrapper.pid"
while true; do
  echo "$(date -Iseconds) starting desk.py" >> "$ROOT/logs/wrapper.log"
  "$ROOT/.venv/bin/python" -u "$ROOT/desk.py" >> "$ROOT/logs/desk.stdout" 2>> "$ROOT/logs/desk.stderr"
  code=$?
  echo "$(date -Iseconds) desk exited $code; restart in 5s" >> "$ROOT/logs/wrapper.log"
  sleep 5
done
