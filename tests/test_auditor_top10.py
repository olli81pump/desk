"""Layer 4 top-10: getTokenLargestAccounts retries, GPA fallback, pool/curve exclusion."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agents.auditor import top10_from_accounts, top10_with_source
import agents.auditor as auditor_mod

FAIL = 0

def check(cond, msg):
    global FAIL
    print(("  PASS " if cond else "  FAIL ") + msg)
    if not cond:
        FAIL += 1


def gpa(pubkey, owner, ui):
    return {
        "pubkey": pubkey,
        "account": {
            "data": {
                "parsed": {
                    "info": {
                        "owner": owner,
                        "tokenAmount": {"uiAmount": ui, "uiAmountString": str(ui)},
                    }
                }
            }
        },
    }


class FakeRpc:
    def __init__(self, largest=None, largest_exc=None, accs=None, accs_exc=None, owners=None):
        self.largest = largest
        self.largest_exc = largest_exc
        self.accs = accs
        self.accs_exc = accs_exc
        self.owners = owners or {}
        self.largest_calls = 0
        self.gpa_calls = 0

    async def get_token_largest(self, mint):
        self.largest_calls += 1
        if self.largest_exc:
            raise self.largest_exc
        return list(self.largest or [])

    async def get_program_accounts_for_mint(self, mint, timeout=60.0):
        self.gpa_calls += 1
        if self.accs_exc:
            raise self.accs_exc
        return list(self.accs or [])

    async def get_account_info(self, pubkey, retries=1):
        owner = self.owners.get(pubkey)
        if owner is None:
            return None
        return {"data": {"parsed": {"info": {"owner": owner}}}}


def main():
    print("test_auditor_top10")
    auditor_mod.bonding_curve_pda = lambda mint: "CURVE1111111111111111111111111111111111111"

    # 11 holder accounts + a huge pool ATA and a curve ATA that must be dropped
    accs = [
        gpa("poolATA", "POOLXXXX", 500),
        gpa("curveATA", "CURVE1111111111111111111111111111111111111", 200),
        gpa("h1", "w1", 100),
        gpa("h2", "w2", 90),
        gpa("h3", "w3", 80),
        gpa("h4", "w4", 70),
        gpa("h5", "w5", 60),
        gpa("h6", "w6", 50),
        gpa("h7", "w7", 40),
        gpa("h8", "w8", 30),
        gpa("h9", "w9", 20),
        gpa("h10", "w10", 10),
        gpa("h11", "w11", 1),  # 11th, not in top 10
        gpa("zero", "wz", 0),
    ]
    # top 10 after exclusion: 100+90+80+70+60+50+40+30+20+10 = 550 / 1000 = 55%
    pct = top10_from_accounts(accs, "Mint111111111111111111111111111111111111111", "POOLXXXX", 1000)
    check(pct is not None and abs(pct - 55.0) < 1e-9, f"GPA top10 excludes pool+curve = 55% ({pct})")

    # empty / missing data
    check(top10_from_accounts([], "m", "p", 1000) is None, "empty GPA -> None")
    check(top10_from_accounts(accs, "m", "p", None) is None, "no supply -> None")

    async def run():
        # largest succeeds (retries=1), do not need GPA
        largest = [{"address": "h1", "uiAmount": 25}, {"address": "h2", "uiAmount": 25}]
        rpc = FakeRpc(largest=largest, owners={"h1": "w1", "h2": "w2"})
        t10, src = await top10_with_source(rpc, "mint", "POOL", 100, retries=1)
        check(src == "getTokenLargestAccounts" and t10 is not None and abs(t10 - 50.0) < 1e-9, f"largest path {t10} {src}")
        check(rpc.largest_calls == 1 and rpc.gpa_calls == 0, "largest hit does not fetch GPA")

        # largest empty then retries exhausted, fallback to provided accounts
        rpc2 = FakeRpc(largest=[], accs=accs)
        t10b, srcb = await top10_with_source(
            rpc2, "Mint111111111111111111111111111111111111111", "POOLXXXX", 1000,
            accounts=accs, retries=1,
        )
        check(srcb == "getProgramAccounts" and t10b is not None and abs(t10b - 55.0) < 1e-9, f"GPA fallback {t10b} {srcb}")
        check(rpc2.gpa_calls == 0, "provided accounts are reused, no second GPA fetch")

        # largest raises, GPA fetched inside helper
        rpc3 = FakeRpc(largest_exc=RuntimeError("no data"), accs=accs)
        t10c, srcc = await top10_with_source(
            rpc3, "Mint111111111111111111111111111111111111111", "POOLXXXX", 1000, retries=1,
        )
        check(srcc == "getProgramAccounts" and abs((t10c or 0) - 55.0) < 1e-9, f"largest error -> GPA {t10c} {srcc}")
        check(rpc3.gpa_calls == 1, "GPA fetched after largest failure")

        # both fail
        rpc4 = FakeRpc(largest_exc=RuntimeError("empty"), accs_exc=RuntimeError("gpa down"))
        t10d, srcd = await top10_with_source(rpc4, "mint", "POOL", 1000, retries=1)
        check(t10d is None and srcd is None, f"both fail -> no data ({t10d}, {srcd})")

        # retries: 3 failed largest calls, then GPA
        rpc5 = FakeRpc(largest_exc=RuntimeError("flaky"), accs=accs)
        t10e, srce = await top10_with_source(
            rpc5, "Mint111111111111111111111111111111111111111", "POOLXXXX", 1000, retries=3,
        )
        check(rpc5.largest_calls == 3 and srce == "getProgramAccounts", f"retried largest 3 times then GPA ({rpc5.largest_calls}, {srce})")

    asyncio.run(run())


if __name__ == "__main__":
    main()
    sys.exit(1 if FAIL else 0)
