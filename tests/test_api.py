from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from leash.api import app, get_catalog, get_gateway, get_store
from leash.catalog import CatalogError, StaticCatalog
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
def catalog():
    return StaticCatalog()


@pytest.fixture
def client(store, gateway, catalog):
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_gateway] = lambda: gateway
    app.dependency_overrides[get_catalog] = lambda: catalog
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def spend(client, amount, payee="northwind", category="office-supplies", **extra):
    body = {"payee": payee, "category": category, "amount": str(amount), **extra}
    return client.post(f"{MANDATE}/attempts", json=body).json()


# -- basics ---------------------------------------------------------------


def test_health_reports_which_gateway_is_live(client):
    body = client.get("/health").json()

    assert body["status"] == "ok"
    assert body["gateway"] == "simulated"
    assert body["catalog"] == "static"
    assert body["paypal_configured"] is False


# -- the specification is a contract --------------------------------------


def _response_schema(operation: dict) -> dict:
    ok = operation.get("responses", {}).get("200") or operation.get(
        "responses", {}
    ).get("201", {})
    return (ok.get("content", {}).get("application/json", {}) or {}).get("schema", {})


def test_every_endpoint_describes_what_it_returns(client):
    # The specification gets published as an SDK and as context an AI agent
    # reads to learn this API. An endpoint that describes no response shape
    # becomes an untyped bag in every generated client.
    spec = client.get("/openapi.json").json()

    vague = []
    for path, operations in spec["paths"].items():
        for verb, operation in operations.items():
            schema = _response_schema(operation)
            named = schema.get("$ref") or schema.get("items", {}).get("$ref")
            if not named:
                vague.append(f"{verb.upper()} {path}")

    assert not vague, f"endpoints with no described response: {vague}"


def test_the_committed_definition_matches_the_api():
    # api/openapi.json is what APIMatic builds the SDK, the portal and the
    # Context Plugin from. A stale copy would teach an agent an API that no
    # longer exists, which is worse than teaching it nothing.
    from scripts.export_openapi import DEFAULT, render

    assert DEFAULT.exists(), "run scripts/export_openapi.py"
    assert DEFAULT.read_text(encoding="utf-8") == render(), (
        "api/openapi.json is out of date, run scripts/export_openapi.py"
    )


def test_the_refusal_contract_is_in_the_specification(client):
    # An agent integrating against this has to learn three things from the
    # spec alone: it gets a verdict, it gets every rule that fired, and it
    # gets told what would have cleared.
    spec = client.get("/openapi.json").json()
    decision = spec["components"]["schemas"]["AttemptOut"]["properties"]

    assert {"verdict", "failed_codes", "max_allowable", "trace"} <= set(decision)
    assert "boundary" in decision["max_allowable"]["description"]

    check = spec["components"]["schemas"]["CheckOut"]["properties"]
    assert {"code", "outcome", "severity", "detail", "evidence"} <= set(check)


# -- the catalogue --------------------------------------------------------


def test_searching_the_catalogue_returns_buyable_things(client):
    body = client.get("/catalog/search", params={"q": "chair"}).json()

    assert body["catalog"] == "static"
    assert body["items"]
    first = body["items"][0]
    assert first["title"]
    assert first["best"]["amount"] > 0
    assert first["best"]["currency"] == "USD"


def test_a_search_makes_its_merchants_payable(client):
    before = {p["id"] for p in client.get("/payees").json()}

    client.get("/catalog/search", params={"q": "desk"})

    after = {p["id"] for p in client.get("/payees").json()}
    assert "northwind_com" in after - before


def test_a_merchants_hostnames_are_one_counterparty(client):
    client.get("/catalog/search", params={"q": "desk"})

    payees = {p["id"]: p["counterparty"] for p in client.get("/payees").json()}

    assert payees["northwind_com"] == "northwind"


def test_a_ceiling_narrows_the_search(client):
    body = client.get(
        "/catalog/search", params={"q": "chair", "under": "100.00"}
    ).json()

    assert body["items"]
    assert all(item["best"]["amount"] <= 10000 for item in body["items"])


def test_an_empty_query_is_refused(client):
    assert client.get("/catalog/search", params={"q": "  "}).status_code == 422


def test_an_unreachable_catalogue_is_a_502(client, catalog):
    class Dead:
        name = "dead"

        async def search(self, query, *, under=None, limit=8):
            raise CatalogError("could not reach Channel3")

    app.dependency_overrides[get_catalog] = lambda: Dead()

    response = client.get("/catalog/search", params={"q": "chair"})

    assert response.status_code == 502
    assert "could not reach" in response.json()["detail"]


# -- shopping -------------------------------------------------------------


def test_the_agent_buys_something_inside_the_mandate(client):
    body = client.post(f"{MANDATE}/shop", json={"needs": ["paper"]}).json()

    step = body["steps"][0]
    assert step["action"] == "bought"
    assert step["decision"]["verdict"] == "allow"
    assert body["summary"]["held"] == 3800


def test_a_refusal_sends_the_agent_back_to_the_shop(client):
    # The 150 chair is over the demo mandate's 100 per-item cap, so the agent
    # reshops under 100 and buys the 88 one instead.
    body = client.post(f"{MANDATE}/shop", json={"needs": ["chair"]}).json()

    step = body["steps"][0]
    assert step["action"] == "reshopped"
    assert step["ceiling"] == 10000
    assert step["first_choice"]["best"]["amount"] == 15000
    assert step["offer"]["amount"] == 8800
    assert body["summary"]["held"] == 8800


def test_reshopping_can_be_turned_off_over_the_wire(client):
    body = client.post(
        f"{MANDATE}/shop", json={"needs": ["chair"], "reshop": False}
    ).json()

    assert body["steps"][0]["action"] == "refused"
    assert body["summary"]["held"] == 0


def test_what_the_agent_bought_can_then_be_paid_out(client):
    # The whole point of registering merchants: a thing the agent found in a
    # shop has to be payable without anyone adding a payee by hand.
    client.post(f"{MANDATE}/shop", json={"needs": ["paper"]})
    charges = client.get(f"{MANDATE}/charges").json()
    held = [c["id"] for c in charges if c["state"] == "pending"]

    response = client.post(f"{MANDATE}/payouts", json={"charge_ids": held})

    assert response.status_code == 200
    assert response.json()["settled_charge_ids"] == held


def test_an_out_of_scope_find_is_refused_with_a_reason(client):
    body = client.post(f"{MANDATE}/shop", json={"needs": ["speaker"]}).json()

    step = body["steps"][0]
    assert step["action"] == "refused"
    assert "category_not_allowed" in step["decision"]["failed_codes"]


# -- reconciliation -------------------------------------------------------


def test_reconciling_corrects_a_payout_that_came_back(client, gateway):
    # Settle honestly, then have the processor change its mind, which is the
    # one thing that cannot be noticed without asking again.
    spend(client, "80.00")
    held = [
        c["id"]
        for c in client.get(f"{MANDATE}/charges").json()
        if c["state"] == "pending"
    ]
    batch_id = client.post(
        f"{MANDATE}/payouts", json={"charge_ids": held}
    ).json()["batch"]["batch_id"]
    assert client.get(MANDATE).json()["committed"] == 8000

    gateway.set_item_status(batch_id, held[0], "RETURNED")
    report = client.post(f"/payouts/{batch_id}/reconcile").json()

    assert report["clean"] is False
    assert report["corrected"][0]["was"] == "settled"
    assert report["corrected"][0]["now"] == "failed"
    assert report["corrected"][0]["processor_status"] == "RETURNED"
    # And the budget is free again.
    assert client.get(MANDATE).json()["committed"] == 0


def test_reconciling_a_healthy_batch_changes_nothing(client):
    spend(client, "80.00")
    held = [
        c["id"]
        for c in client.get(f"{MANDATE}/charges").json()
        if c["state"] == "pending"
    ]
    batch_id = client.post(
        f"{MANDATE}/payouts", json={"charge_ids": held}
    ).json()["batch"]["batch_id"]

    report = client.post(f"/payouts/{batch_id}/reconcile").json()

    assert report["clean"] is True
    assert report["agreed"] == 1
    assert client.get(MANDATE).json()["committed"] == 8000


def test_reconciling_everything_reports_across_batches(client):
    spend(client, "80.00")
    held = [
        c["id"]
        for c in client.get(f"{MANDATE}/charges").json()
        if c["state"] == "pending"
    ]
    client.post(f"{MANDATE}/payouts", json={"charge_ids": held})

    body = client.post("/payouts/reconcile").json()

    assert body["clean"] is True
    assert len(body["batches"]) == 1


def test_reconciling_an_unknown_batch_is_a_502(client):
    assert client.post("/payouts/nope/reconcile").status_code == 502


def test_shopping_an_unknown_mandate_is_a_404(client):
    response = client.post("/mandates/mnd_nope/shop", json={"needs": ["paper"]})

    assert response.status_code == 404


def test_an_empty_needs_list_is_refused(client):
    assert client.post(f"{MANDATE}/shop", json={"needs": []}).status_code == 422


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
    assert terms["allowed_categories"] == ["furniture", "office-supplies"]
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
