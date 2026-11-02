from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest

from leash.config import Settings, settings
from leash.models import Attempt, Charge, ChargeState, Mandate
from leash.money import Money

NOW = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def hermetic_settings(monkeypatch):
    """No test ever reads the credentials on this machine.

    Several tests assert what happens with no PayPal key, and they passed for
    weeks only because nobody had one yet. The moment a real `.env` appeared
    they started testing the developer's laptop instead of the code. So the
    file and the LEASH_ variables are both taken away for the duration.
    """
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for name in [n for n in os.environ if n.startswith("LEASH_")]:
        monkeypatch.delenv(name, raising=False)
    settings.cache_clear()
    yield
    settings.cache_clear()


def usd(major: str | int) -> Money:
    return Money.from_major(major, "USD")


def ago(seconds: int) -> datetime:
    return NOW - timedelta(seconds=seconds)


def a_mandate(**overrides) -> Mandate:
    fields = {
        "id": "mnd_1",
        "agent_id": "agent_shopper",
        "currency": "USD",
        "total_limit": usd(500),
        "starts_at": NOW - timedelta(days=1),
        "ends_at": NOW + timedelta(days=1),
        "per_item_limit": usd(100),
    }
    fields.update(overrides)
    return Mandate(**fields)


def an_attempt(amount: Money | None = None, **overrides) -> Attempt:
    fields = {
        "id": "att_1",
        "mandate_id": "mnd_1",
        "payee": "acme",
        "category": "office",
        "amount": amount if amount is not None else usd(50),
        "requested_at": NOW,
    }
    fields.update(overrides)
    return Attempt(**fields)


def a_charge(amount: Money, **overrides) -> Charge:
    fields = {
        "id": "chg_old",
        "mandate_id": "mnd_1",
        "payee": "acme",
        "category": "office",
        "amount": amount,
        "created_at": ago(60),
        "state": ChargeState.SETTLED,
    }
    fields.update(overrides)
    return Charge(**fields)
