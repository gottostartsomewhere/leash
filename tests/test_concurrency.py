"""Limits hold when the attempts arrive at the same time.

Every other test in this suite sends one attempt, waits for the answer, and
sends the next, which is exactly the situation in which a check-then-hold
cannot go wrong. The API is not like that. It serves `authorize` from a
thread pool and `release_payouts` from an event loop, so two requests can be
inside the ledger at once, and before the ledger took a lock they did:

- thirty-two retries of one idempotency key made thirty-two holds;
- a burst cleared seven charges through a pace limit of six, and with the
  scheduler pushed harder, thirty;
- two payout requests for the same charges sent them to PayPal twice, and
  the second only found out when settling failed, after the money had gone.

Thread scheduling is turned right down for the burst tests. That does not
create a race, it stops a rare one from hiding, and without the lock these
fail on almost every run. With it the answers are exact, so nothing here is
flaky in the passing direction.
"""

from __future__ import annotations

import asyncio
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import httpx
import pytest
from conftest import a_mandate, an_attempt, usd

from leash.api import app, get_gateway, get_store
from leash.ledger import IllegalTransition, Ledger
from leash.models import Attempt, ChargeState, Velocity
from leash.money import Money
from leash.payouts import SimulatedGateway
from leash.store import DEMO_MANDATE_ID, build_demo_store

THREADS = 32
BURSTS = 8


@pytest.fixture(autouse=True)
def tight_scheduling():
    before = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    yield
    sys.setswitchinterval(before)


def burst(work, n: int = THREADS):
    """Run `work(i)` on n threads that all leave the starting line together."""
    gate = threading.Barrier(n)

    def one(i):
        gate.wait()
        return work(i)

    with ThreadPoolExecutor(n) as pool:
        return list(pool.map(one, range(n)))


# -- authorize --------------------------------------------------------------


def test_one_idempotency_key_retried_at_once_holds_once():
    for _ in range(BURSTS):
        ledger = Ledger(a_mandate())
        decisions = burst(
            lambda i: ledger.authorize(
                an_attempt(usd(40), id=f"att_{i}", idempotency_key="retry-me")
            )
        )

        assert len(ledger.charges()) == 1
        assert ledger.held == usd(40)
        # Every retry is answered with the first decision, not a new one.
        assert len({d.attempt.id for d in decisions}) == 1


def test_a_burst_cannot_spend_past_the_total():
    # $90 each against $500, to thirty-two different merchants so that no
    # per-merchant rule is what stops it. Five fit. A sixth would be $540.
    for _ in range(BURSTS):
        ledger = Ledger(a_mandate())
        decisions = burst(
            lambda i: ledger.authorize(an_attempt(usd(90), id=f"att_{i}", payee=f"m{i}"))
        )

        assert sum(d.allowed for d in decisions) == 5
        assert ledger.committed == usd(450)
        assert ledger.committed <= ledger.mandate.total_limit


def test_a_burst_cannot_beat_the_pace_limit():
    for _ in range(BURSTS):
        ledger = Ledger(a_mandate(velocity=Velocity(window_seconds=60, max_count=6)))
        decisions = burst(
            lambda i: ledger.authorize(an_attempt(usd(5), id=f"att_{i}", payee=f"m{i}"))
        )

        assert sum(d.allowed for d in decisions) == 6


def test_reading_while_another_thread_writes_does_not_raise():
    # Iterating the charges while another thread inserts one used to raise
    # "dictionary changed size during iteration", which reached the screen
    # as a 500 on whichever request happened to be reading.
    ledger = Ledger(a_mandate(total_limit=usd(100_000), per_item_limit=usd(1_000)))

    def work(i):
        if i % 2:
            ledger.authorize(an_attempt(usd(1), id=f"att_{i}", payee=f"m{i}"))
        for _ in range(50):
            ledger.summary()
            ledger.rows()

    burst(work)


# -- claiming holds for a payout --------------------------------------------


def _ledger_with_two_holds() -> Ledger:
    ledger = Ledger(a_mandate())
    ledger.authorize(an_attempt(usd(40), id="att_a", payee="a"))
    ledger.authorize(an_attempt(usd(30), id="att_b", payee="b"))
    return ledger


def test_a_claimed_hold_cannot_be_claimed_again():
    ledger = _ledger_with_two_holds()
    ledger.claim(["chg_att_a"])

    with pytest.raises(IllegalTransition, match="already being paid out"):
        ledger.claim(["chg_att_a"])


def test_only_one_of_many_simultaneous_claims_wins():
    for _ in range(BURSTS):
        ledger = _ledger_with_two_holds()

        def work(i):
            try:
                ledger.claim(["chg_att_a"])
                return True
            except IllegalTransition:
                return False

        assert sum(burst(work)) == 1


def test_a_claim_is_all_or_nothing():
    ledger = _ledger_with_two_holds()
    ledger.claim(["chg_att_b"])

    with pytest.raises(IllegalTransition):
        ledger.claim(["chg_att_a", "chg_att_b"])
    # The one that could have been claimed was not left claimed.
    assert not ledger.in_flight("chg_att_a")


def test_a_charge_named_twice_in_one_payout_is_claimed_once():
    ledger = _ledger_with_two_holds()
    claimed = ledger.claim(["chg_att_a", "chg_att_a"])

    assert [c.id for c in claimed] == ["chg_att_a"]


def test_a_claimed_hold_cannot_be_released_from_under_its_payout():
    ledger = _ledger_with_two_holds()
    ledger.claim(["chg_att_a"])

    with pytest.raises(IllegalTransition, match="being paid out"):
        ledger.release("chg_att_a")


def test_revocation_leaves_a_claimed_hold_to_its_payout():
    ledger = _ledger_with_two_holds()
    ledger.claim(["chg_att_a"])

    dropped = ledger.revoke()

    assert [c.id for c in dropped] == ["chg_att_b"]
    # Still held, still counting, and the payout can still settle it,
    # because the money may already be moving.
    assert ledger.charge("chg_att_a").state is ChargeState.PENDING
    assert ledger.settle("chg_att_a").state is ChargeState.SETTLED


def test_unclaiming_hands_the_hold_back():
    ledger = _ledger_with_two_holds()
    ledger.claim(["chg_att_a"])
    ledger.unclaim(["chg_att_a"])

    assert ledger.release("chg_att_a").state is ChargeState.RELEASED


# -- the payout endpoint ----------------------------------------------------


class SlowGateway(SimulatedGateway):
    """A processor that takes its time, like a real one, and counts calls."""

    def __init__(self) -> None:
        super().__init__()
        self.sends = 0

    async def send(self, items, *, batch_id):
        self.sends += 1
        await asyncio.sleep(0.2)
        return await super().send(items, batch_id=batch_id)


def test_two_payouts_for_the_same_charge_send_the_money_once():
    store = build_demo_store()
    gateway = SlowGateway()
    ledger = store.ledger(DEMO_MANDATE_ID)
    decision = ledger.authorize(
        Attempt(
            id="att_race",
            mandate_id=DEMO_MANDATE_ID,
            payee="northwind",
            category="office-supplies",
            amount=Money.from_major("40", "USD"),
            requested_at=datetime.now(timezone.utc),
        )
    )
    assert decision.allowed

    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_gateway] = lambda: gateway

    async def both():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://leash") as c:
            body = {"charge_ids": ["chg_att_race"]}
            path = f"/mandates/{DEMO_MANDATE_ID}/payouts"
            return await asyncio.gather(c.post(path, json=body), c.post(path, json=body))

    try:
        first, second = asyncio.run(both())
    finally:
        app.dependency_overrides.clear()

    assert sorted([first.status_code, second.status_code]) == [200, 409]
    assert gateway.sends == 1
    assert ledger.charge("chg_att_race").state is ChargeState.SETTLED
    assert not ledger.in_flight("chg_att_race")


def test_a_processor_that_refuses_hands_the_holds_back():
    from leash.payouts import PayoutError

    class Refusing(SimulatedGateway):
        async def send(self, items, *, batch_id):
            raise PayoutError("processor said no")

    store = build_demo_store()
    ledger = store.ledger(DEMO_MANDATE_ID)
    ledger.authorize(
        Attempt(
            id="att_retry",
            mandate_id=DEMO_MANDATE_ID,
            payee="northwind",
            category="office-supplies",
            amount=Money.from_major("40", "USD"),
            requested_at=datetime.now(timezone.utc),
        )
    )
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_gateway] = lambda: Refusing()

    async def once():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://leash") as c:
            return await c.post(
                f"/mandates/{DEMO_MANDATE_ID}/payouts",
                json={"charge_ids": ["chg_att_retry"]},
            )

    try:
        response = asyncio.run(once())
    finally:
        app.dependency_overrides.clear()

    # Refused, still held, and free to be retried rather than stuck claimed.
    assert response.status_code == 502
    assert ledger.charge("chg_att_retry").state is ChargeState.PENDING
    assert not ledger.in_flight("chg_att_retry")
