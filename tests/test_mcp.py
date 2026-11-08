"""An outside agent, on a Leash, over the Model Context Protocol.

These go through the whole app the way Claude or ChatGPT would reach it:
JSON-RPC posted to /mcp, through the FastAPI lifespan that starts the
session manager, past the Host check, into the tools, and into the same
ledger the HTTP routes read. Each one pins something that was wrong, or
that would be wrong in production and invisible on localhost.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from leash.api import app, get_catalog, get_gateway, get_store
from leash.catalog import StaticCatalog
from leash.payouts import SimulatedGateway
from leash.store import DEMO_MANDATE_ID, build_demo_store

PRODUCTION_HOST = "leash-api-sm0h.onrender.com"
TOOLS = {"read_mandate", "search_products", "request_purchase", "recent_decisions"}


@pytest.fixture
def store():
    return build_demo_store()


@pytest.fixture
def client(store):
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_gateway] = lambda: SimulatedGateway()
    app.dependency_overrides[get_catalog] = lambda: StaticCatalog()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def rpc(client, method, params=None, *, host=PRODUCTION_HOST):
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
        headers={"Accept": "application/json, text/event-stream", "Host": host},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "error" not in body, body
    return body["result"]


def tool(client, name, **arguments):
    result = rpc(client, "tools/call", {"name": name, "arguments": arguments})
    assert not result.get("isError"), result
    data = result.get("structuredContent")
    if data is None:
        data = json.loads(result["content"][0]["text"])
    return data.get("result", data) if isinstance(data, dict) else data


# -- reaching it ------------------------------------------------------------


def test_it_answers_on_the_production_host(client):
    # DNS-rebinding protection switches itself on for a localhost server and
    # then accepts only a localhost Host header. Left on, every request that
    # reached Render would have been refused, and nothing on a laptop would
    # have shown it.
    assert rpc(client, "tools/list", host=PRODUCTION_HOST)["tools"]


def test_an_outside_agent_sees_exactly_four_tools(client):
    names = {t["name"] for t in rpc(client, "tools/list")["tools"]}
    assert names == TOOLS


def test_no_tool_can_move_money(client):
    # The point of the surface. An agent can ask; a person releases.
    names = {t["name"] for t in rpc(client, "tools/list")["tools"]}
    for forbidden in ("pay", "payout", "release", "approve", "settle", "revoke", "transfer"):
        assert not any(forbidden in name for name in names), forbidden


def test_the_instructions_tell_the_agent_how_this_works(client):
    result = rpc(
        client,
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "0"},
        },
    )
    text = result["instructions"]
    assert "cannot move money" in text
    assert "largest amount that would have cleared" in text


# -- reading ----------------------------------------------------------------


def test_the_mandate_is_read_in_money_not_minor_units(client):
    mandate = tool(client, "read_mandate")

    assert mandate["available"] == "500.00 USD"
    assert mandate["terms"]["per_purchase"] == "100.00 USD"
    assert set(mandate["terms"]["categories"]) == {"furniture", "office-supplies"}


def test_a_search_says_how_to_buy_and_makes_the_merchant_payable(client, store):
    found = tool(client, "search_products", query="desk")["results"]

    assert found
    first = found[0]
    assert first["payee"] and first["category"] and first["amount"]
    assert store.knows_payee(first["payee"])


# -- asking -----------------------------------------------------------------


def test_a_refusal_says_what_would_clear_in_real_money(client):
    # The decision carries money as minor units. Passed through raw, an agent
    # was told the largest that would clear was "10000", which an agent that
    # takes the field literally reads as ten thousand dollars.
    d = tool(
        client, "request_purchase", payee="northwind", amount="150", category="office-supplies"
    )

    assert d["verdict"] == "block"
    assert d["largest_that_would_clear"] == "100.00 USD"
    assert {"rule": "per_item_limit"} .items() <= d["refused_by"][0].items()


def test_an_allowed_purchase_is_held_and_nothing_is_paid(client, store):
    d = tool(
        client, "request_purchase", payee="northwind", amount="40", category="office-supplies"
    )

    assert d["verdict"] == "allow"
    assert d["remaining_after"] == "460.00 USD"
    held = [c for c in store.ledger(DEMO_MANDATE_ID).charges() if c.state.value == "pending"]
    assert len(held) == 1
    assert store.batches() == ()


def test_a_purchase_split_across_one_merchants_addresses_is_caught(client):
    first = tool(client, "request_purchase", payee="acme_us", amount="75", category="furniture")
    second = tool(client, "request_purchase", payee="acme_eu", amount="75", category="furniture")

    assert first["verdict"] == "allow"
    assert second["verdict"] == "block"
    assert "structuring" in [r["rule"] for r in second["refused_by"]]


def test_a_retry_with_one_key_holds_once(client, store):
    for _ in range(3):
        tool(
            client,
            "request_purchase",
            payee="northwind",
            amount="40",
            category="office-supplies",
            idempotency_key="same-request",
        )

    assert len(store.ledger(DEMO_MANDATE_ID).charges()) == 1


def test_an_unknown_payee_is_an_error_not_a_guess(client):
    result = rpc(
        client,
        "tools/call",
        {
            "name": "request_purchase",
            "arguments": {"payee": "nobody_we_know", "amount": "10", "category": "furniture"},
        },
    )

    assert result["isError"]
    assert "search_products" in result["content"][0]["text"]


def test_an_outside_agents_purchase_lands_in_the_same_audit_log(client):
    # The screen reads the HTTP API. If the agent endpoint wrote to a
    # different store, a judge would watch their agent spend and see nothing.
    tool(client, "request_purchase", payee="northwind", amount="40", category="office-supplies")

    rows = client.get(f"/mandates/{DEMO_MANDATE_ID}/decisions").json()
    rows = rows if isinstance(rows, list) else rows.get("decisions", rows)
    assert any(r["payee"] == "northwind" and r["verdict"] == "allow" for r in rows)

    recent = tool(client, "recent_decisions", limit=1)["decisions"]
    assert recent[0]["amount"] == "40.00 USD"
