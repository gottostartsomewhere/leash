from __future__ import annotations

import pytest
from conftest import a_charge, a_mandate, usd

from leash.ledger import IllegalTransition
from leash.models import ChargeState
from leash.payouts import PayoutItemResult, PayoutResult, holds_money
from leash.reconcile import reconcile_all, reconcile_batch
from leash.store import Payee, Store

BATCH = "BATCH_1"


class Canned:
    """A processor that says whatever the test needs it to say."""

    name = "canned"

    def __init__(self, *items: tuple[str, str], status: str = "SUCCESS"):
        self._result = PayoutResult(
            batch_id=BATCH,
            status=status,
            gateway=self.name,
            items=tuple(
                PayoutItemResult(charge_id=cid, status=st, payout_item_id=f"it_{cid}")
                for cid, st in items
            ),
        )

    async def send(self, items, *, batch_id):  # pragma: no cover - unused here
        return self._result

    async def status(self, batch_id):
        return self._result


def a_store(*charges, mandate=None) -> tuple[Store, object]:
    store = Store()
    store.add_payee(Payee(id="acme", name="Acme", email="acme@example.com"))
    ledger = store.open(mandate or a_mandate(), charges=charges)
    store.record_batch(
        PayoutResult(batch_id=BATCH, status="PENDING", gateway="canned")
    )
    return store, ledger


# -- which statuses keep the money ----------------------------------------


@pytest.mark.parametrize(
    "status", ["SUCCESS", "PENDING", "PROCESSING", "UNCLAIMED", "ONHOLD", "success"]
)
def test_these_statuses_mean_the_money_is_with_them(status):
    assert holds_money(status)


@pytest.mark.parametrize(
    "status",
    ["FAILED", "RETURNED", "REVERSED", "REFUNDED", "BLOCKED", "CANCELED", "DENIED"],
)
def test_these_statuses_mean_the_money_came_back(status):
    assert not holds_money(status)


def test_a_status_nobody_has_seen_is_not_assumed_to_have_paid():
    # Failing closed: a status we do not recognise is not a reason to keep
    # claiming a payment succeeded.
    assert not holds_money("SOMETHING_NEW")
    assert not holds_money("")


# -- the case this exists for ---------------------------------------------


async def test_a_settled_payout_that_came_back_is_corrected():
    # Settled honestly on acceptance, returned an hour later. Nothing tells
    # us; we have to ask.
    store, ledger = a_store(
        a_charge(usd(100), id="chg_1", state=ChargeState.SETTLED)
    )
    assert ledger.available == usd(400)

    report = await reconcile_batch(store, Canned(("chg_1", "RETURNED")), BATCH)

    assert not report.clean
    assert len(report.corrected) == 1
    correction = report.corrected[0]
    assert (correction.was, correction.now) == ("settled", "failed")
    assert correction.processor_status == "RETURNED"
    assert ledger.charge("chg_1").state is ChargeState.FAILED


async def test_the_budget_comes_back_with_it():
    store, ledger = a_store(
        a_charge(usd(100), id="chg_1", state=ChargeState.SETTLED)
    )

    await reconcile_batch(store, Canned(("chg_1", "FAILED")), BATCH)

    assert ledger.available == usd(500)
    assert ledger.committed == usd(0)


async def test_a_batch_the_ledger_already_agrees_with_changes_nothing():
    store, ledger = a_store(
        a_charge(usd(100), id="chg_1", state=ChargeState.SETTLED),
        a_charge(usd(50), id="chg_2", state=ChargeState.SETTLED),
    )

    report = await reconcile_batch(
        store, Canned(("chg_1", "SUCCESS"), ("chg_2", "SUCCESS")), BATCH
    )

    assert report.clean
    assert report.agreed == 2
    assert report.corrected == ()
    assert ledger.committed == usd(150)
    assert "already agreed" in report.summary()


async def test_only_the_item_that_came_back_is_touched():
    store, ledger = a_store(
        a_charge(usd(100), id="chg_1", state=ChargeState.SETTLED),
        a_charge(usd(50), id="chg_2", state=ChargeState.SETTLED),
    )

    report = await reconcile_batch(
        store, Canned(("chg_1", "SUCCESS"), ("chg_2", "RETURNED")), BATCH
    )

    assert [c.charge_id for c in report.corrected] == ["chg_2"]
    assert ledger.charge("chg_1").state is ChargeState.SETTLED
    assert ledger.charge("chg_2").state is ChargeState.FAILED
    assert ledger.committed == usd(100)


# -- the other direction ---------------------------------------------------


async def test_a_hold_the_processor_says_paid_is_caught_up():
    # We never recorded the capture, but the money went out.
    store, ledger = a_store(
        a_charge(usd(100), id="chg_1", state=ChargeState.PENDING)
    )

    report = await reconcile_batch(store, Canned(("chg_1", "SUCCESS")), BATCH)

    assert [(c.was, c.now) for c in report.corrected] == [("pending", "settled")]
    assert ledger.charge("chg_1").state is ChargeState.SETTLED
    assert ledger.held == usd(0)


async def test_a_hold_the_processor_rejected_is_failed():
    store, ledger = a_store(
        a_charge(usd(100), id="chg_1", state=ChargeState.PENDING)
    )

    await reconcile_batch(store, Canned(("chg_1", "DENIED")), BATCH)

    assert ledger.charge("chg_1").state is ChargeState.FAILED
    assert ledger.available == usd(500)


async def test_money_that_went_out_on_a_charge_we_gave_back_needs_a_person():
    # The dangerous direction. Re-committing budget that may since have been
    # spent elsewhere could push the mandate past its own limit, so this is
    # reported and not fixed.
    store, ledger = a_store(
        a_charge(usd(100), id="chg_1", state=ChargeState.RELEASED)
    )

    report = await reconcile_batch(store, Canned(("chg_1", "SUCCESS")), BATCH)

    assert report.corrected == ()
    assert len(report.conflicts) == 1
    assert report.conflicts[0].processor_status == "SUCCESS"
    assert ledger.charge("chg_1").state is ChargeState.RELEASED
    assert "need a person" in report.summary()


async def test_a_charge_this_process_never_saw_is_reported():
    store, _ = a_store()

    report = await reconcile_batch(store, Canned(("chg_ghost", "SUCCESS")), BATCH)

    assert report.unknown == ("chg_ghost",)
    assert not report.clean


# -- the transition itself -------------------------------------------------


def test_only_a_settled_charge_can_come_back():
    _, ledger = a_store(a_charge(usd(100), id="chg_1", state=ChargeState.PENDING))

    with pytest.raises(IllegalTransition, match="only a settled charge"):
        ledger.reverse("chg_1")


def test_reversing_twice_is_refused():
    _, ledger = a_store(a_charge(usd(100), id="chg_1", state=ChargeState.SETTLED))
    ledger.reverse("chg_1")

    with pytest.raises(IllegalTransition):
        ledger.reverse("chg_1")


# -- every batch -----------------------------------------------------------


async def test_reconciling_everything_covers_each_batch():
    store, ledger = a_store(
        a_charge(usd(100), id="chg_1", state=ChargeState.SETTLED)
    )

    reports = await reconcile_all(store, Canned(("chg_1", "RETURNED")))

    assert len(reports) == 1
    assert reports[0].batch_id == BATCH
    assert ledger.charge("chg_1").state is ChargeState.FAILED


async def test_the_fresh_result_replaces_what_we_recorded():
    store, _ = a_store(a_charge(usd(100), id="chg_1", state=ChargeState.SETTLED))
    assert store.batch(BATCH).status == "PENDING"

    await reconcile_batch(store, Canned(("chg_1", "SUCCESS"), status="SUCCESS"), BATCH)

    assert store.batch(BATCH).status == "SUCCESS"
