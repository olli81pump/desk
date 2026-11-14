# Grok Bot Desk (PAPER)

Paper trading desk for Pump.fun graduations on PumpSwap. It never places an order, never loads a private key, and never signs or sends a transaction. Buys and sells happen only when you tap a button in [FOMO](https://fomo.family/r/olli81).

## App

Public site: https://olli81pump.github.io/desk/

Open it once as `https://olli81pump.github.io/desk/#d=…` using the value stored in `.secrets/DATA_PATH` on this box. The app saves that path in `localStorage` (`desk_data_path`) and then polls `state.json` every 60 seconds with a cache-busting `?ts=` query. Do not put the path in source or config files.

Settings, pause, and mode changes go through Telegram (Account tab is read-only). Notifier is Telegram; web push is not available on this plan B host.

## Process

```sh
# start (restart wrapper + nohup)
nohup scripts/run_desk.sh >/workspace/desk/logs/wrapper.nohup 2>&1 &

# stop
kill "$(cat logs/wrapper.pid)" "$(cat logs/desk.pid)"
```

Heartbeats live in the SQLite db (`data/desk.db`, gitignored).

## Data publish strategy

The static app lives in `docs/` on `main`. Live `state.json` is published every 60 seconds by **force-pushing a single orphan commit** to the `pages` branch. GitHub Pages is served from `pages` `/`. This keeps `main` history from bloating. The publisher is `publisher.py` (DATA_PATH is read from `.secrets` only).

## Routines you need to create

These scripts exist but the routines cannot be created from this box:

- Hourly: `scripts/health_check.py` — restart stale agents, Telegram if something was down, warn on >10 websocket reconnects/hour.
- Daily 08:00 Europe/Berlin: `scripts/night_report.py` — writes `logs/reports/YYYY-MM-DD.md` (+ `.json`) for a morning Page, then clears `db.skips`.
