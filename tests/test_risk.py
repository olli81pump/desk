"""Acceptance 3: trail / stop / timeout / stops never move down; per-position stop."""
from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agents.risk import evaluate, tighter_stop, pnl
import settings as S

s = S.fresh()
FAIL = 0

def check(cond, msg):
    global FAIL
    print(("  PASS " if cond else "  FAIL ") + msg)
    if not cond:
        FAIL += 1


def pos(entry=1.0, peak=1.0, stop=6.0, trail_active=False, opened=None, **kw):
    return {
        "entry_price": entry,
        "peak_price": peak,
        "stop_pct": stop,
        "trail_active": trail_active,
        "opened_at": opened or datetime.now(timezone.utc).isoformat(),
        **kw,
    }


def main():
    print("test_risk")
    now = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
    # +25% then 13% off the top = trail exit
    # trail starts at +20%, trail exits at 12% off peak
    p = pos(entry=100, peak=100, opened=now.isoformat())
    ev = evaluate(p, 125, now, s)  # +25%
    check(ev["trail_active"] and ev["reason"] is None, f"+25% arms trail, no exit yet {ev}")
    p2 = dict(p, peak_price=ev["peak"], trail_active=ev["trail_active"])
    ev2 = evaluate(p2, 125 * (1 - 0.13), now, s)  # 13% off the top = 108.75
    check(ev2["reason"] == "trail", f"13% off top = trail ({ev2})")

    # -6.1% = stop
    evs = evaluate(pos(entry=100, peak=100, stop=6, opened=now.isoformat()), 93.9, now, s)
    check(evs["reason"] == "stop", f"-6.1% = stop ({evs})")

    # 3h at +4% = timeout (min gain 5%)
    opened = now - timedelta(hours=3, seconds=1)
    evt = evaluate(pos(entry=100, peak=104, opened=opened.isoformat()), 104, now, s)
    check(evt["reason"] == "timeout", f"3h at +4% = timeout ({evt})")

    # loosening the stop never moves an open stop down
    # open at 6%, setting goes to 8% (looser) -> tighter_stop keeps 6? 
    # Wait: tighter means a *larger* stop_pct? No.
    # "Never moves a stop down. A new stop setting applies to new positions, and to open ones only if it is tighter."
    # stop down = allowing more loss, i.e. increasing stop_pct from 6 to 8 is loosening (stop line moves down).
    # tighter = smaller stop_pct (e.g. 6 -> 4), stop line moves up.
    # I implemented tighter_stop as max(old, new) which is WRONG if tighter means smaller percent.
    #
    # "set stop to -8%", a position opened at -6% still shows -6%.
    # So going from 6 to 8 is loosening and must NOT apply to open positions.
    # Tighter would be 6 -> 5, which SHOULD apply.
    #
    # I need to fix tighter_stop and desk.py risk loop!
    check(True, "see tighter_stop checks below")


if __name__ == "__main__":
    main()
    # These document the intended semantics; implementation is patched if needed.
    # loosening 6 -> 8 must keep 6
    # tighter 6 -> 4 must become 4
    sys.path.insert(0, str(ROOT))
    from agents import risk as risk_mod
    # After fix, tighter_stop(6, 8) == 6 and tighter_stop(6, 4) == 4
    a = risk_mod.tighter_stop(6, 8)
    b = risk_mod.tighter_stop(6, 4)
    print("  tighter_stop(6,8)=", a, "tighter_stop(6,4)=", b)
    check = globals()["check"]
    check(a == 6, "loosening 6->8 stays 6 on an open position")
    check(b == 4, "tightening 6->4 applies 4")
    # per-position: open at -6% still -6% after setting -8%
    now = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
    ev = risk_mod.evaluate(pos(entry=100, peak=100, stop=6, opened=now.isoformat()), 91.9, now, s)
    check(ev["reason"] == "stop", "position opened at -6% still stops at -6% (91.9)")
    ev8 = risk_mod.evaluate(pos(entry=100, peak=100, stop=8, opened=now.isoformat()), 93.9, now, s)
    check(ev8["reason"] != "stop", "new -8% position does not stop at -6.1% / 93.9")
    ev81 = risk_mod.evaluate(pos(entry=100, peak=100, stop=8, opened=now.isoformat()), 91.9, now, s)
    ev82 = risk_mod.evaluate(pos(entry=100, peak=100, stop=8, opened=now.isoformat()), 100 * (1-0.081), now, s)
    check(ev82["reason"] == "stop", f"new position stops at -8.1% ({ev82})")
    sys.exit(1 if FAIL else 0)
