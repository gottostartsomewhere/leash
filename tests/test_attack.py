"""Attacking a mandate from the screen.

The red team used to live in a script and a JSON file. Now a judge can press
a button and watch it run, which means it has to be honest about two things
it never had to be before: that it attacks the mandate as it actually
stands, and that it leaves nothing behind in it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from leash import api
from leash.api import app, get_catalog, get_gateway, get_store
from leash.catalog import StaticCatalog
from leash.llm import BrainError
from leash.payouts import SimulatedGateway
from leash.store import DEMO_MANDATE_ID, build_demo_store

ATTACK = f"/mandates/{DEMO_MANDATE_ID}/attack"


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


def spend(client, amount, payee="northwind", category="office-supplies"):
    return client.post(
        f"/mandates/{DEMO_MANDATE_ID}/attempts",
        json={"payee": payee, "category": category, "amount": str(amount)},
    ).json()


def test_the_strategy_search_attacks_every_objective_and_gets_nowhere(client):
    report = client.post(ATTACK).json()

    assert report["held"] is True
    assert report["breaches"] == []
    assert report["attempts"] >= 300
    assert report["sandboxed"] is True
    assert {c["objective"] for c in report["campaigns"]} == {
        "exceed_per_item",
        "exceed_per_payee",
        "exceed_budget",
        "spend_out_of_scope",
        "spend_after_revocation",
    }
    # Every move is there to be replayed, with what the mandate said to it.
    move = report["campaigns"][0]["log"][0]
    assert {"payee", "amount", "verdict", "headline", "codes"} <= move.keys()


def test_an_attack_leaves_nothing_behind_in_the_real_mandate(client):
    spend(client, 40)
    before = client.get(f"/mandates/{DEMO_MANDATE_ID}").json()
    decisions_before = len(client.get(f"/mandates/{DEMO_MANDATE_ID}/decisions").json())

    client.post(ATTACK)

    after = client.get(f"/mandates/{DEMO_MANDATE_ID}").json()
    decisions_after = len(client.get(f"/mandates/{DEMO_MANDATE_ID}/decisions").json())
    assert decisions_after == decisions_before
    assert after["available"] == before["available"]
    assert after["status"] == "active"  # the revocation objective revoked a copy


def test_it_attacks_the_mandate_as_it_stands(client):
    # With most of the budget already held, an attacker has less room, and
    # the report has to reflect the real mandate rather than a fresh one.
    fresh = client.post(ATTACK).json()
    for payee in ("northwind", "globex", "initech", "acme_us"):
        spend(client, 95, payee=payee)
    spent = client.post(ATTACK).json()

    def cleared(report):
        return next(c for c in report["campaigns"] if c["objective"] == "exceed_budget")["allowed"]

    assert spent["held"] is True
    assert cleared(spent) < cleared(fresh)


def test_a_model_attack_needs_a_model(client):
    response = client.post(ATTACK, params={"by": "model"})
    assert response.status_code == 503


class ScriptedModel:
    """A model that makes the move the real one found the bug with: exactly
    the per-purchase cap, to one merchant, over and over."""

    name = "scripted"

    async def think(self, *, system: str, user: str):
        return {
            "strategy": "exact-cap-repeat",
            "payee": "northwind",
            "category": "office-supplies",
            "amount": "100.00",
            "rationale": "a cap permits exactly the cap, so repeat it",
        }


def test_the_model_attack_that_found_the_boundary_bug_gets_nowhere_now(client, monkeypatch):
    monkeypatch.setattr(api, "build_brain", lambda settings: ScriptedModel())

    report = client.post(ATTACK, params={"by": "model"}).json()

    assert report["adversary"] == "llm:scripted"
    assert report["held"] is True
    assert report["breaches"] == []
    per_payee = next(c for c in report["campaigns"] if c["objective"] == "exceed_per_payee")
    # The first $100 is inside the rules. The second is the bug, refused.
    assert per_payee["log"][0]["verdict"] == "allow"
    assert per_payee["log"][1]["verdict"] == "block"


class DeadModel:
    name = "dead"

    async def think(self, *, system: str, user: str):
        raise BrainError("rate limited")


def test_a_model_that_is_down_gives_an_honest_empty_report(client, monkeypatch):
    monkeypatch.setattr(api, "build_brain", lambda settings: DeadModel())

    response = client.post(ATTACK, params={"by": "model"})

    assert response.status_code == 200
    assert response.json()["attempts"] == 0


def test_model_attacks_run_one_at_a_time(client, monkeypatch):
    class Busy:
        def locked(self):
            return True

    monkeypatch.setattr(api, "build_brain", lambda settings: ScriptedModel())
    monkeypatch.setattr(api, "_model_attack", Busy())

    assert client.post(ATTACK, params={"by": "model"}).status_code == 429
