"""Drive the demo scenario end to end and narrate it.

Run it with `python scripts/walkthrough.py`. No server, no credentials: it
mounts the app in process against the simulated gateway. This is the rehearsal
for the three minutes, in the order the video needs it.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from leash.api import app, get_gateway, get_store  # noqa: E402
from leash.payouts import SimulatedGateway  # noqa: E402
from leash.store import DEMO_MANDATE_ID, build_demo_store  # noqa: E402

MANDATE = f"/mandates/{DEMO_MANDATE_ID}"
RULE = "-" * 68


def money(minor: int) -> str:
    return f"${minor / 100:,.2f}"


def beat(title: str) -> None:
    print(f"\n{RULE}\n{title}\n{RULE}")


def main() -> int:
    store = build_demo_store()
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_gateway] = lambda: SimulatedGateway()
    client = TestClient(app)

    def spend(amount: str, payee: str, category: str = "office-supplies") -> dict:
        body = client.post(
            f"{MANDATE}/attempts",
            json={
                "payee": payee,
                "category": category,
                "amount": amount,
                "description": f"{category} from {payee}",
            },
        ).json()
        verdict = "ALLOW" if body["verdict"] == "allow" else "BLOCK"
        print(f"  [{verdict:5}] {money(body['amount']):>10} to {payee:10} {category}")
        print(f"          {body['reason']}")
        if body["verdict"] == "block" and body["max_allowable"]:
            print(f"          would have cleared at {money(body['max_allowable'])}")
        return body

    mandate = client.get(MANDATE).json()
    beat("THE MANDATE")
    print(f"  agent        {mandate['agent_id']}")
    print(f"  budget       {money(mandate['total_limit'])}")
    print("  per item     $100.00")
    print("  per payee    $200.00")
    print("  categories   office-supplies, furniture")
    print("  pace         6 charges or $400 per minute")
    print("  one payee    at most 60% of the book, once $200 is committed")

    beat("1. IT WORKS. Spending inside the rules.")
    allowed = [
        spend("80.00", "northwind"),
        spend("64.50", "globex", "furniture"),
    ]

    beat("2. IT GETS TOLD NO. Over the cap, and out of scope.")
    spend("150.00", "initech")
    spend("45.00", "initech", "electronics")

    beat("3. IT TRIES TO BE CLEVER. One merchant, two addresses.")
    print("  Acme is one merchant with a US and an EU receiver address.")
    print("  A $120 purchase does not fit under a $100 cap. So: two charges.")
    spend("60.00", "acme_us")
    blocked = spend("60.00", "acme_eu")
    evidence = next(
        row["evidence"] for row in blocked["trace"] if row["code"] == "structuring"
    )
    print(f"\n          counterparty    {evidence['group']}")
    print(f"          cluster         {evidence['cluster_size']} charges")
    print(f"          total           {money(evidence['cluster_total'])}")
    print(f"          over the cap by {money(evidence['over_by'])}")
    print(f"          confidence      {evidence['confidence']}")

    beat("4. IT RUNS AWAY WITH ITSELF. Six charges a minute, then nothing.")
    print("  Each of these is small, in scope, and under every cap.")
    print("  A budget spent correctly in nine seconds is still a loop.")
    for _ in range(4):
        if spend("10.00", "initech")["verdict"] == "block":
            break

    beat("5. THE MONEY MOVES. One batch, human-approved.")
    charge_ids = [f"chg_{body['attempt_id']}" for body in allowed]
    payout = client.post(f"{MANDATE}/payouts", json={"charge_ids": charge_ids}).json()
    print(f"  batch   {payout['batch']['batch_id']}")
    print(f"  status  {payout['batch']['status']} via {payout['batch']['gateway']}")
    for item in payout["batch"]["items"]:
        print(f"    {item['status']:8} {item['charge_id']}")

    beat("6. THE LEASH COMES OFF THE WALL. Revoked mid-flight.")
    before = client.get(f"{MANDATE}/charges").json()
    pending = [c for c in before if c["state"] == "pending"]
    print(f"  {len(pending)} holds are live, none of them captured yet:")
    for charge in pending:
        print(f"    {charge['amount']['display']:>12}  {charge['payee']}")

    revoked = client.post(f"{MANDATE}/revoke").json()
    print(f"\n  revoked. holds dropped: {len(revoked['released_charge_ids'])}")
    spend("5.00", "northwind")

    summary = client.get(MANDATE).json()
    beat("THE LEDGER")
    print(f"  attempts   {summary['attempts']}")
    print(f"  blocked    {summary['blocked']}")
    print(f"  committed  {money(summary['committed'])}")
    print(f"  available  {money(summary['available'])}")
    print(f"  status     {summary['status']}")
    print(
        f"\n  Every other demo shows you what their agent can buy."
        f"\n  {summary['blocked']} of {summary['attempts']} attempts here never happened.\n"
    )

    app.dependency_overrides.clear()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
