"""Acceptance 5: freeze authority set -> red at layer 2, layers 3-8 not checked."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agents.auditor import run_audit
import settings as S


class FakeRpc:
    def __init__(self, freeze):
        self.freeze = freeze

    async def get_account_info(self, mint, retries=3):
        return {
            "owner": "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb",
            "data": {
                "parsed": {
                    "info": {
                        "mintAuthority": None,
                        "freezeAuthority": self.freeze,
                        "supply": "1000000",
                        "decimals": 6,
                    },
                    "type": "mint",
                },
                "program": "spl-token-2022",
            },
        }


class FakeSources:
    async def rug_report(self, mint):
        raise AssertionError("layer 5 should not be reached")

    async def rug_graph(self, mint):
        raise AssertionError("layer 7 should not be reached")

    async def dexscreener(self, mints):
        raise AssertionError("should not be reached")


async def main() -> int:
    print("test_auditor_freeze")
    s = S.fresh()
    result = await run_audit(
        "MintFreeze111",
        {"mint": "MintFreeze111", "creator": "Dev111", "migrated_at": "2020-01-01T00:00:00+00:00", "pool": "Pool111"},
        s,
        FakeRpc(freeze="SomeAuthority11111111111111111111111111111"),
        FakeSources(),
    )
    layers = result["layers"]
    print("  layers:", [(L["n"], L["pass"], L["value"]) for L in layers])
    ok = (
        result["passed"] is False
        and result["layersChecked"] == 2
        and layers[0]["n"] == 1 and layers[0]["pass"] is True
        and layers[1]["n"] == 2 and layers[1]["pass"] is False and layers[1]["value"] == "freeze not revoked"
        and all(L.get("value") == "not checked" and L.get("pass") is None for L in layers[2:])
        and len(layers) == 8
        and result["reason"] == "freeze not revoked"
    )
    print("  PASS" if ok else "  FAIL", "freeze red at layer 2, 3-8 not checked")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
