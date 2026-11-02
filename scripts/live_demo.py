"""Run the whole scenario over HTTP, against whatever gateway is configured.

    python scripts/live_demo.py            # attempts only
    python scripts/live_demo.py --pay      # and release the holds as one batch

`scripts/walkthrough.py` narrates the same story in process, with no server.
This one goes through the API, so with PayPal credentials set it moves real
sandbox money and reconciles the batch item by item.

Each beat carries what it is supposed to do, so this is a check rather than a
demonstration. A beat that comes back with a different verdict or a different
set of rules is reported as a mismatch and the script exits non-zero.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from leash.store import DEMO_MANDATE_ID  # noqa: E402

#: payee, category, amount, expected verdict, expected rules, what it shows
BEATS: tuple[tuple[str, str, str, str, tuple[str, ...], str], ...] = (
    ("northwind", "office", "40.00", "allow", (),
     "Inside every rule. The normal case, and it should look boring."),
    ("globex", "hardware", "150.00", "block", ("per_item_limit",),
     "Over the per-item cap, and it says what would clear instead."),
    ("globex", "hardware", "100.00", "allow", (),
     "The agent takes the counter-offer."),
    ("acme_us", "office", "75.00", "allow", (),
     "75 to Acme. Under the cap on its own."),
    ("acme_eu", "office", "75.00", "block", ("structuring",),
     "Same merchant, second address. Each charge passes; the cluster does not."),
    ("initech", "electronics", "60.00", "block", ("category_not_allowed",),
     "Out of scope. No amount fixes the wrong category."),
    ("northwind", "office", "20.00", "allow", (), ""),
    ("globex", "office", "20.00", "allow", (), ""),
    ("initech", "office", "20.00", "allow", (), ""),
    ("acme_us", "office", "20.00", "block", ("velocity",),
     "Seventh hold inside a minute. The pace limit, on its own."),
    ("globex", "hardware", "500.00", "block",
     ("per_item_limit", "per_payee_limit", "insufficient_budget", "velocity",
      "concentration"),
     "Every check runs, so a refusal names every reason, not the first."),
)

SETTLED = {"SUCCESS", "PENDING", "PROCESSING", "UNCLAIMED"}


def money(minor: int) -> str:
    return f"{minor / 100:,.2f}"


def run(base: str, pace: float, pay: bool) -> int:
    client = httpx.Client(base_url=base, timeout=60.0)
    mandate = f"/mandates/{DEMO_MANDATE_ID}"

    health = client.get("/health").json()
    print(f"gateway   {health['gateway']}")
    print(f"catalog   {health['catalog']}")
    print()

    client.post("/demo/reset")

    mismatches: list[str] = []
    print(f"{'#':>2}  {'VERDICT':<7} {'PAYEE':<10} {'AMOUNT':>8}  RULES")
    print("-" * 78)

    for index, (payee, category, amount, want, want_rules, note) in enumerate(
        BEATS, start=1
    ):
        decision = client.post(
            f"{mandate}/attempts",
            json={
                "payee": payee,
                "category": category,
                "amount": amount,
                "description": note[:120],
            },
        ).json()

        got = decision["verdict"]
        got_rules = tuple(decision["failed_codes"])
        flag = " "
        if got != want or set(got_rules) != set(want_rules):
            flag = "!"
            mismatches.append(
                f"beat {index}: wanted {want} {sorted(want_rules)}, "
                f"got {got} {sorted(got_rules)}"
            )

        print(
            f"{index:>2}{flag} {got:<7} {payee:<10} {amount:>8}  "
            f"{', '.join(got_rules) or 'inside every rule'}"
        )
        if got == "block" and decision["max_allowable"] > 0:
            print(f"      {money(decision['max_allowable'])} would have cleared")
        if note:
            print(f"      {note}")
        time.sleep(pace)

    summary = client.get(mandate).json()
    charges = client.get(f"{mandate}/charges").json()
    held = [c["id"] for c in charges if c["state"] == "pending"]

    print()
    print(f"{summary['attempts']} asked, {summary['blocked']} refused, "
          f"{len(held)} holds standing, {money(summary['held'])} not yet moved")

    if mismatches:
        print()
        for line in mismatches:
            print(f"MISMATCH  {line}")
        return 1

    if not pay:
        print("\n(pass --pay to release the holds as one batch)")
        return 0

    print(f"\nreleasing {len(held)} holds as one batch...")
    response = client.post(f"{mandate}/payouts", json={"charge_ids": held})
    if response.status_code != 200:
        print(f"payout failed ({response.status_code}): {response.text[:400]}")
        return 1

    result = response.json()
    batch_id = result["batch"]["batch_id"]
    print(f"batch     {batch_id}")
    print(f"settled   {len(result['settled_charge_ids'])}")
    print(f"failed    {len(result['failed_charge_ids'])}")

    # The create response carries only a batch header. The items arrive on a
    # later read, which is the one that says what actually happened.
    for attempt in range(8):
        time.sleep(4)
        batch = client.get(f"/payouts/{batch_id}").json()
        items = batch.get("items") or []
        if items:
            print(f"\nstatus    {batch['status']}")
            print(f"{'ITEM':<22} {'CHARGE':<28} STATUS")
            print("-" * 78)
            for item in items:
                print(
                    f"{item.get('payout_item_id', '?'):<22} "
                    f"{item['charge_id']:<28} {item['status']}"
                )
            unpaid = [i for i in items if i["status"].upper() not in SETTLED]
            return 1 if unpaid else 0
        print(f"  waiting, batch is {batch.get('status')}")

    print("batch never reported its items")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--pace", type=float, default=0.4)
    parser.add_argument("--pay", action="store_true")
    args = parser.parse_args()
    return run(args.base, args.pace, args.pay)


if __name__ == "__main__":
    raise SystemExit(main())
