from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from leash.api import app, get_gateway, get_store
from leash.payouts import SimulatedGateway
from leash.store import DEMO_MANDATE_ID, build_demo_store

MANDATE = f"/mandates/{DEMO_MANDATE_ID}"


@pytest.fixture
def store():
    return build_demo_store()


@pytest.fixture
def gateway():
    return SimulatedGateway()


@pytest.fixture
def client(store, gateway):
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_gateway] = lambda: gateway
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def spend(client, amount, payee="northwind", category="office", **extra):
    body = {"payee": payee, "category": category, "amount": str(amount), **extra}
    return client.post(f"{MANDATE}/attempts", json=body).json()


# -- basics ---------------------------------------------------------------


def test_health_reports_which_gateway_is_live(client):
    body = client.get("/health").json()

    assert body["status"] == "ok"
    assert body["gateway"] == "simulated"
    assert body["paypal_configured"] is False


def test_an_unknown_mandate_is_a_404(client):
    assert client.get("/mandates/mnd_nope").status_code == 404


def test_a_mandate_reports_its_terms_not_just_its_balance(client):
    # Balances say how much is left. A person handing authority to an agent has
    # to be able to read back what that authority actually is.
    body = client.get(MANDATE).json()

    assert body["available"] == 50000
    terms = body["terms"]
    assert terms["per_item_limit"] == 10000
    assert terms["per_payee_limit"] == 20000
    assert terms["allowed_categories"] == ["hardware", "office"]
    assert terms["velocity"] == {
        "window_seconds": 60,
        "max_count": 6,
        "max_amount": 40000,
    }
    assert terms["concentration_max_share"] == 0.6
    assert terms["concentration_floor"] == 20000
    assert terms["structuring_window_seconds"] == 900
    assert terms["revoked_at"] is None


def test_revoking_shows_up_in_the_terms(client):
    client.post(f"{MANDATE}/revoke")

    terms = client.get(MANDATE).json()["terms"]

    assert terms["revoked_at"] is not None


def test_the_demo_payees_include_two_addresses_for_one_merchant(client):
    payees = {p["id"]: p["counterparty"] for p in client.get("/payees").json()}

    assert payees["acme_us"] == "acme"
    assert payees["acme_eu"] == "acme"


# -- authorizing ----------------------------------------------------------


def test_an_in_scope_spend_is_allowed_and_holds_the_money(client):
    body = spend(client, 80)

    assert body["verdict"] == "allow"
    assert body["summary"]["held"] == 8000
    assert body["summary"]["available"] == 42000


def test_over_the_cap_is_blocked_with_a_reason(client):
    body = spend(client, 150)

    assert body["verdict"] == "block"
    assert "per_item_limit" in body["failed_codes"]
    assert body["max_allowable"] == 10000


def test_out_of_scope_category_is_blocked(client):
    body = spend(client, 40, category="electronics")

    assert body["failed_codes"] == ["category_not_allowed"]
    assert body["max_allowable"] == 0


def test_splitting_across_one_merchants_two_addresses_is_caught(client):
    first = spend(client, 60, payee="acme_us")
    second = spend(client, 60, payee="acme_eu")

    assert first["verdict"] == "allow"
    assert second["verdict"] == "block"
    assert second["failed_codes"][0] == "structuring"
    assert second["trace"][6]["evidence"]["group"] == "acme"


def test_a_blocked_attempt_still_lands_in_the_audit_trail(client):
    spend(client, 150)
    rows = client.get(f"{MANDATE}/decisions").json()

    assert len(rows) == 1
    assert rows[0]["verdict"] == "block"
    assert len(rows[0]["trace"]) == 11


def test_replaying_an_idempotency_key_does_not_hold_twice(client):
    spend(client, 80, idempotency_key="k1")
    body = spend(client, 80, idempotency_key="k1")

    assert body["summary"]["held"] == 8000
    assert len(client.get(f"{MANDATE}/charges").json()) == 1


def test_concentration_waits_until_the_book_is_big_enough_to_judge(client):
    # 60% cap, but the first payee is always 100% of a book of one.
    body = spend(client, 90, payee="globex")

    assert body["verdict"] == "allow"


# -- approving and paying -------------------------------------------------


def test_approving_holds_sends_one_batch_and_settles_them(client):
    a = spend(client, 80, payee="northwind")
    b = spend(client, 70, payee="globex")
    charge_ids = [f"chg_{a['attempt_id']}", f"chg_{b['attempt_id']}"]

    body = client.post(
        f"{MANDATE}/payouts", json={"charge_ids": charge_ids}
    ).json()

    assert body["batch"]["status"] == "SUCCESS"
    assert sorted(body["settled_charge_ids"]) == sorted(charge_ids)
    assert body["summary"]["held"] == 0
    assert body["summary"]["committed"] == 15000


def test_a_failed_item_is_marked_failed_not_settled(client, gateway, store):
    gateway._fail = frozenset({store.payee("globex").email})
    a = spend(client, 80, payee="northwind")
    b = spend(client, 70, payee="globex")
    charge_ids = [f"chg_{a['attempt_id']}", f"chg_{b['attempt_id']}"]

    body = client.post(f"{MANDATE}/payouts", json={"charge_ids": charge_ids}).json()

    assert body["settled_charge_ids"] == [f"chg_{a['attempt_id']}"]
    assert body["failed_charge_ids"] == [f"chg_{b['attempt_id']}"]
    # The failed one gave its budget back.
    assert body["summary"]["committed"] == 8000


def test_paying_an_already_settled_charge_is_a_conflict(client):
    a = spend(client, 80)
    charge_id = f"chg_{a['attempt_id']}"
    client.post(f"{MANDATE}/payouts", json={"charge_ids": [charge_id]})

    again = client.post(f"{MANDATE}/payouts", json={"charge_ids": [charge_id]})

    assert again.status_code == 409


def test_paying_an_unknown_charge_is_a_404(client):
    response = client.post(f"{MANDATE}/payouts", json={"charge_ids": ["chg_nope"]})

    assert response.status_code == 404


def test_a_batch_can_be_looked_up_afterwards(client):
    a = spend(client, 80)
    batch_id = client.post(
        f"{MANDATE}/payouts", json={"charge_ids": [f"chg_{a['attempt_id']}"]}
    ).json()["batch"]["batch_id"]

    body = client.get(f"/payouts/{batch_id}").json()

    assert body["batch_id"] == batch_id
    assert body["settled"] is True


# -- declining and revoking ----------------------------------------------


def test_declining_a_hold_returns_the_budget(client):
    a = spend(client, 80)

    body = client.post(f"/charges/chg_{a['attempt_id']}/release").json()

    assert body["charge"]["state"] == "released"
    assert body["summary"]["available"] == 50000


def test_revoking_drops_the_holds_and_nothing_clears_after(client):
    a = spend(client, 80)

    revoked = client.post(f"{MANDATE}/revoke").json()
    after = spend(client, 10)

    assert revoked["released_charge_ids"] == [f"chg_{a['attempt_id']}"]
    assert revoked["summary"]["status"] == "revoked"
    assert after["failed_codes"] == ["mandate_inactive"]


def test_revoking_leaves_settled_money_alone(client):
    a = spend(client, 80)
    client.post(f"{MANDATE}/payouts", json={"charge_ids": [f"chg_{a['attempt_id']}"]})

    body = client.post(f"{MANDATE}/revoke").json()

    assert body["released_charge_ids"] == []
    assert body["summary"]["committed"] == 8000


# -- demo control ---------------------------------------------------------


def test_reset_puts_the_scenario_back(client):
    spend(client, 80)

    body = client.post("/demo/reset").json()

    assert body["reset"] is True
    assert client.get(MANDATE).json()["attempts"] == 0
    assert client.get(MANDATE).json()["available"] == 50000


def test_a_mandate_can_be_created_over_the_wire(client):
    body = client.post(
        "/mandates",
        json={
            "agent_id": "agent_test",
            "total_limit": "250.00",
            "per_item_limit": "40.00",
            "concentration_max_share": 0.5,
            "concentration_floor": "100.00",
            "velocity": {"window_seconds": 30, "max_count": 3},
        },
    ).json()

    assert body["total_limit"] == 25000
    assert body["available"] == 25000


def test_an_impossible_mandate_is_rejected(client):
    response = client.post(
        "/mandates",
        json={
            "agent_id": "agent_test",
            "total_limit": "250.00",
            "concentration_floor": "100.00",
        },
    )

    assert response.status_code == 422
