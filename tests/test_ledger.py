from __future__ import annotations

import pytest
from conftest import NOW, a_mandate, an_attempt, usd

from leash.ledger import IllegalTransition, Ledger, OverCapture, UnknownCharge
from leash.models import ChargeState, CheckCode


def test_an_allowed_attempt_holds_the_money():
    ledger = Ledger(a_mandate())
    decision = ledger.authorize(an_attempt(usd(80)))

    assert decision.allowed
    assert ledger.held == usd(80)
    assert ledger.committed == usd(80)
    assert ledger.available == usd(420)


def test_a_blocked_attempt_holds_nothing():
    ledger = Ledger(a_mandate())
    decision = ledger.authorize(an_attempt(usd(150)))

    assert not decision.allowed
    assert ledger.charges() == ()
    assert ledger.available == usd(500)


def test_releasing_a_hold_gives_the_budget_back():
    ledger = Ledger(a_mandate())
    ledger.authorize(an_attempt(usd(80)))
    released = ledger.release("chg_att_1")

    assert released.state is ChargeState.RELEASED
    assert ledger.available == usd(500)
    assert ledger.held == usd(0)


def test_a_failed_charge_gives_the_budget_back():
    ledger = Ledger(a_mandate())
    ledger.authorize(an_attempt(usd(80)))
    ledger.fail("chg_att_1")

    assert ledger.available == usd(500)


def test_settling_keeps_the_money_committed():
    ledger = Ledger(a_mandate())
    ledger.authorize(an_attempt(usd(80)))
    settled = ledger.settle("chg_att_1")

    assert settled.state is ChargeState.SETTLED
    assert ledger.committed == usd(80)
    assert ledger.held == usd(0)
    assert ledger.available == usd(420)


def test_capturing_less_than_the_hold_returns_the_difference():
    ledger = Ledger(a_mandate())
    ledger.authorize(an_attempt(usd(80)))
    ledger.settle("chg_att_1", usd(55))

    assert ledger.committed == usd(55)
    assert ledger.available == usd(445)


def test_capturing_more_than_the_hold_is_refused():
    ledger = Ledger(a_mandate())
    ledger.authorize(an_attempt(usd(80)))

    with pytest.raises(OverCapture):
        ledger.settle("chg_att_1", usd(90))


def test_a_settled_charge_cannot_be_settled_again():
    ledger = Ledger(a_mandate())
    ledger.authorize(an_attempt(usd(80)))
    ledger.settle("chg_att_1")

    with pytest.raises(IllegalTransition):
        ledger.settle("chg_att_1")


def test_an_unknown_charge_is_an_error():
    ledger = Ledger(a_mandate())

    with pytest.raises(UnknownCharge):
        ledger.release("chg_nope")


def test_a_hold_stops_the_same_budget_being_spent_twice():
    # Without holds, both of these see the full 500 and both pass.
    ledger = Ledger(a_mandate(per_item_limit=None))
    first = ledger.authorize(an_attempt(usd(300), id="att_a"))
    second = ledger.authorize(an_attempt(usd(300), id="att_b", payee="other"))

    assert first.allowed
    assert not second.allowed
    assert CheckCode.INSUFFICIENT_BUDGET in {r.code for r in second.failures}


def test_replaying_an_idempotency_key_changes_nothing():
    ledger = Ledger(a_mandate())
    key = "idem_7f3a"
    first = ledger.authorize(an_attempt(usd(80), id="att_a", idempotency_key=key))
    replay = ledger.authorize(an_attempt(usd(80), id="att_b", idempotency_key=key))

    assert replay is first
    assert len(ledger.charges()) == 1
    assert ledger.available == usd(420)


def test_revoking_drops_every_hold_but_keeps_what_settled():
    ledger = Ledger(a_mandate())
    ledger.authorize(an_attempt(usd(80), id="att_a"))
    ledger.authorize(an_attempt(usd(70), id="att_b", payee="other"))
    ledger.settle("chg_att_a")

    dropped = ledger.revoke(at=NOW)

    assert [c.id for c in dropped] == ["chg_att_b"]
    assert ledger.charge("chg_att_a").state is ChargeState.SETTLED
    assert ledger.committed == usd(80)


def test_nothing_clears_after_revocation():
    ledger = Ledger(a_mandate())
    ledger.revoke(at=NOW)
    decision = ledger.authorize(an_attempt(usd(10), id="att_late"))

    assert not decision.allowed
    assert decision.headline.code is CheckCode.MANDATE_INACTIVE


def test_the_summary_counts_what_happened():
    ledger = Ledger(a_mandate())
    ledger.authorize(an_attempt(usd(80), id="att_a"))
    ledger.authorize(an_attempt(usd(150), id="att_b"))

    summary = ledger.summary()
    assert summary["attempts"] == 2
    assert summary["blocked"] == 1
    assert summary["available"] == 42000


def test_every_decision_lands_in_the_audit_rows():
    ledger = Ledger(a_mandate())
    ledger.authorize(an_attempt(usd(80), id="att_a"))
    ledger.authorize(an_attempt(usd(150), id="att_b"))

    rows = ledger.rows()
    assert [r["verdict"] for r in rows] == ["allow", "block"]
