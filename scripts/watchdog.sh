#!/bin/bash
# Runs the health check every 2 minutes so a hung desk is restarted fast.
cd "$(dirname "$0")/.."
while true; do
  sleep 120
  .venv/bin/python scripts/health_check.py >> logs/watchdog.log 2>&1
done
