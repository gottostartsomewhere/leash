"""Writing a mandate in plain English.

The model drafts and the engine decides, so most of what is tested here is
the second half: that a draft is held to the same rules as a hand-written
mandate, that what it leaves open is said out loud, that it is attacked
before anyone signs it, and that drafting alone changes nothing.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from leash import api
from leash.api import app, get_catalog, get_gateway, get_store
from leash.catalog import StaticCatalog
from leash.drafting import exposure
from leash.llm import BrainError
from leash.models import Mandate
from leash.money import Money
from leash.payouts import SimulatedGateway
from leash.store import DEMO_MANDATE_ID, build_demo_store

TEXT = (
    "Office furniture and supplies only. $300 in total, nothing over $80, "
    "at most 4 purchases a minute, for two weeks."
)


class Scripted:
    """A model that answers with whatever it was given."""

    name = "scripted"

    def __init__(self, reply):
        self.reply = reply

    async def think(self, *, system: str, user: str):
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


GOOD = {
    "total": 300,
    "per_purchase": 80,
    "per_merchant": None,
    "categories": ["furniture", "office-supplies"],
    "max_purchases_per_minute": 4,
    "duration_days": 14,
    "assumptions": ["Read 'office furniture' as the furniture category."],
    "unclear": [],
}


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


def with_model(monkeypatch, reply):
    monkeypatch.setattr(api, "build_brain", lambda settings: Scripted(reply))


def test_a_plain_english_mandate_is_drafted_checked_and_attacked(client, monkeypatch):
    with_model(monkeypatch, GOOD)

    out = client.post("/mandates/draft", json={"text": TEXT}).json()

    terms = out["mandate"]
    assert terms["total_limit"] == "300.00"
    assert terms["per_item_limit"] == "80.00"
    assert terms["per_payee_limit"] is None
    assert terms["allowed_categories"] == ["furniture", "office-supplies"]
    assert terms["velocity"]["max_count"] == 4
    assert terms["duration_hours"] == 14 * 24
    assert out["drafted_by"] == "scripted"
    assert out["attack"]["held"] is True
    assert out["attack"]["attempts"] > 100


def test_what_a_draft_leaves_open_is_said_out_loud(client, monkeypatch):
    # They never mentioned a per-merchant cap, so the model must not invent
    # one, and the draft has to say that everything could go to one place.
    with_model(monkeypatch, GOOD)

    out = client.post("/mandates/draft", json={"text": TEXT}).json()
    lines = {e["label"]: e for e in out["exposure"]}

    assert lines["Most with one merchant"]["loose"] is True
    assert lines["Most with one merchant"]["value"] == "300.00 USD"
    assert lines["Largest single purchase"]["loose"] is False
    assert lines["Largest single purchase"]["value"] == "80.00 USD"
    assert lines["Split purchases"]["value"] == "caught"


def test_a_category_the_catalogue_does_not_use_is_left_out_not_guessed(client, monkeypatch):
    with_model(monkeypatch, {**GOOD, "categories": ["furniture", "gift cards"]})

    out = client.post("/mandates/draft", json={"text": TEXT}).json()

    assert out["mandate"]["allowed_categories"] == ["furniture"]
    assert any("gift cards" in line for line in out["unclear"])


def test_a_missing_end_date_becomes_a_stated_assumption(client, monkeypatch):
    with_model(monkeypatch, {**GOOD, "duration_days": None})

    out = client.post("/mandates/draft", json={"text": TEXT}).json()

    assert out["mandate"]["duration_hours"] == 30 * 24
    assert any("30 days" in line for line in out["assumptions"])


def test_a_draft_with_no_total_is_refused(client, monkeypatch):
    with_model(monkeypatch, {**GOOD, "total": None})

    response = client.post("/mandates/draft", json={"text": TEXT})

    assert response.status_code == 422
    assert "how much" in response.json()["detail"]


def test_a_draft_is_held_to_the_same_rules_as_a_hand_written_mandate(client, monkeypatch):
    with_model(monkeypatch, {**GOOD, "per_purchase": -5})

    assert client.post("/mandates/draft", json={"text": TEXT}).status_code == 422


def test_drafting_needs_a_model(client):
    assert client.post("/mandates/draft", json={"text": TEXT}).status_code == 503


def test_an_unreachable_model_is_not_blamed_on_the_words(client, monkeypatch):
    with_model(monkeypatch, BrainError("rate limited"))

    assert client.post("/mandates/draft", json={"text": TEXT}).status_code == 502


def test_drafting_alone_changes_nothing(client, monkeypatch):
    with_model(monkeypatch, GOOD)
    before = client.get(f"/mandates/{DEMO_MANDATE_ID}").json()

    client.post("/mandates/draft", json={"text": TEXT})

    after = client.get(f"/mandates/{DEMO_MANDATE_ID}").json()
    assert after["terms"] == before["terms"]
    assert after["total_limit"] == before["total_limit"]


def test_the_terms_shown_are_the_terms_signed(client, monkeypatch):
    # The draft's `mandate` goes back unmodified, and the demo then runs on
    # exactly what the person read: nothing filled in on the way.
    with_model(monkeypatch, GOOD)
    drafted = client.post("/mandates/draft", json={"text": TEXT}).json()["mandate"]

    signed = client.post("/demo/mandate", json=drafted)
    live = client.get(f"/mandates/{DEMO_MANDATE_ID}").json()

    assert signed.status_code == 200
    assert live["total_limit"] == 30000
    assert live["terms"]["per_item_limit"] == 8000
    assert live["terms"]["per_payee_limit"] is None
    assert sorted(live["terms"]["allowed_categories"]) == ["furniture", "office-supplies"]
    # And it is enforced, not just recorded.
    over = client.post(
        f"/mandates/{DEMO_MANDATE_ID}/attempts",
        json={"payee": "northwind", "category": "furniture", "amount": "95"},
    ).json()
    assert over["verdict"] == "block"


def test_reset_puts_the_default_mandate_back(client, monkeypatch):
    with_model(monkeypatch, GOOD)
    drafted = client.post("/mandates/draft", json={"text": TEXT}).json()["mandate"]
    client.post("/demo/mandate", json=drafted)

    client.post("/demo/reset")

    assert client.get(f"/mandates/{DEMO_MANDATE_ID}").json()["total_limit"] == 50000


def test_exposure_reads_a_mandate_with_every_cap_missing():
    now = datetime.now(timezone.utc)
    bare = Mandate(
        id="m",
        agent_id="a",
        currency="USD",
        total_limit=Money.from_major(500, "USD"),
        starts_at=now,
        ends_at=now + timedelta(days=3),
    )
    lines = exposure(bare)
    loose = {e.label for e in lines if e.loose}
    # Three days from now, read a moment later, is still three days.
    assert next(e.value for e in lines if e.label == "Expires") == "in 3 days"
    assert loose == {
        "Largest single purchase",
        "Most with one merchant",
        "Most in one minute",
        "Categories",
    }
