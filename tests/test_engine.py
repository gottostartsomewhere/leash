from __future__ import annotations

from datetime import timedelta

import pytest
from conftest import NOW, a_charge, a_mandate, ago, an_attempt, usd

from leash.engine import evaluate
from leash.models import (
    CheckCode,
    ChargeState,
    Outcome,
    PayeeDirectory,
    Velocity,
    Verdict,
)
from leash.money import Money


def codes(decision, outcome=Outcome.FAIL):
    return {r.code for r in decision.trace if r.outcome is outcome}


def result_for(decision, code):
    return next(r for r in decision.trace if r.code is code)


# -- the happy path -------------------------------------------------------


def test_clean_attempt_is_allowed():
    decision = evaluate(a_mandate(), an_attempt(usd(50)))

    assert decision.verdict is Verdict.ALLOW
    assert decision.allowed
    assert decision.failures == ()
    assert decision.headline is None
    assert "Allowed" in decision.reason()


def test_every_check_appears_in_the_trace():
    decision = evaluate(a_mandate(), an_attempt(usd(50)))

    assert {r.code for r in decision.trace} == set(CheckCode)


def test_headroom_on_an_allow_is_the_tightest_cap():
    # 500 budget, 100 per item. The per-item cap binds first.
    decision = evaluate(a_mandate(), an_attempt(usd(50)))

    assert decision.max_allowable == usd(100)


# -- scope and validity ---------------------------------------------------


def test_revoked_mandate_blocks():
    mandate = a_mandate().revoked(at=ago(10))
    decision = evaluate(mandate, an_attempt(usd(10)))

    assert decision.verdict is Verdict.BLOCK
    assert CheckCode.MANDATE_INACTIVE in codes(decision)
    assert decision.max_allowable == usd(0)


def test_currency_mismatch_blocks():
    decision = evaluate(a_mandate(), an_attempt(Money.from_major(50, "INR")))

    assert CheckCode.CURRENCY_MISMATCH in codes(decision)


def test_a_currency_mismatch_stands_down_the_amount_checks():
    # Comparing 50 INR to a 100 USD cap is meaningless, so those checks skip
    # rather than raising out of what is meant to be a pure function.
    decision = evaluate(a_mandate(), an_attempt(Money.from_major(50, "INR")))

    assert result_for(decision, CheckCode.PER_ITEM_LIMIT).outcome is Outcome.SKIP
    assert result_for(decision, CheckCode.INSUFFICIENT_BUDGET).outcome is Outcome.SKIP
    assert decision.failures == (result_for(decision, CheckCode.CURRENCY_MISMATCH),)
    assert decision.max_allowable == usd(0)


@pytest.mark.parametrize("offset", [timedelta(days=-2), timedelta(days=2)])
def test_outside_the_window_blocks(offset):
    attempt = an_attempt(usd(10), requested_at=NOW + offset)
    decision = evaluate(a_mandate(), attempt, now=NOW + offset)

    assert CheckCode.OUTSIDE_WINDOW in codes(decision)
    assert decision.max_allowable == usd(0)


def test_payee_not_on_the_list_blocks():
    mandate = a_mandate(allowed_payees=frozenset({"staples"}))
    decision = evaluate(mandate, an_attempt(usd(10), payee="acme"))

    assert CheckCode.PAYEE_NOT_ALLOWED in codes(decision)


def test_an_allowed_alias_satisfies_the_payee_list():
    mandate = a_mandate(allowed_payees=frozenset({"acme"}))
    directory = PayeeDirectory({"acme_eu": "acme"})
    decision = evaluate(
        mandate, an_attempt(usd(10), payee="acme_eu"), directory=directory
    )

    assert decision.allowed


def test_scope_drift_blocks():
    mandate = a_mandate(allowed_categories=frozenset({"office"}))
    decision = evaluate(mandate, an_attempt(usd(10), category="electronics"))

    failure = result_for(decision, CheckCode.CATEGORY_NOT_ALLOWED)
    assert failure.failed
    assert failure.evidence["category"] == "electronics"


# -- the per-item cap and the split that evades it ------------------------


def test_over_the_per_item_cap_blocks():
    decision = evaluate(a_mandate(), an_attempt(usd(150)))

    assert CheckCode.PER_ITEM_LIMIT in codes(decision)
    assert result_for(decision, CheckCode.PER_ITEM_LIMIT).evidence["over_by"] == 5000


def test_a_plain_breach_is_not_reported_as_structuring():
    decision = evaluate(a_mandate(), an_attempt(usd(150)))

    assert result_for(decision, CheckCode.STRUCTURING).outcome is Outcome.SKIP


def test_two_charges_under_the_cap_that_sum_over_it_are_structuring():
    history = [a_charge(usd(60), created_at=ago(60))]
    decision = evaluate(a_mandate(), an_attempt(usd(60)), history)

    assert decision.verdict is Verdict.BLOCK
    failure = result_for(decision, CheckCode.STRUCTURING)
    assert failure.failed
    assert failure.evidence["cluster_size"] == 2
    assert failure.evidence["cluster_total"] == 12000
    assert failure.evidence["over_by"] == 2000


def test_repeating_a_charge_of_exactly_the_cap_is_structuring():
    # Found by the LLM adversary, missed by the strategy search.
    #
    # The per-item check refuses what is *over* the cap, so a charge of
    # exactly the cap passes it. Structuring used to skip anything that was
    # not *below* the cap, so a charge of exactly the cap skipped that too.
    # Each check assumed the other owned the boundary. Repeat a cap-sized
    # charge and any amount at all reaches one merchant, 100 at a time.
    history = [a_charge(usd(100), created_at=ago(60))]
    decision = evaluate(a_mandate(), an_attempt(usd(100)), history)

    assert decision.verdict is Verdict.BLOCK
    failure = result_for(decision, CheckCode.STRUCTURING)
    assert failure.failed
    assert failure.evidence["cluster_total"] == 20000
    assert failure.evidence["over_by"] == 10000


def test_a_single_charge_of_exactly_the_cap_is_still_fine():
    # The fix must not turn the boundary into a refusal. One charge at the
    # cap is exactly what the cap permits.
    decision = evaluate(a_mandate(), an_attempt(usd(100)))

    assert decision.verdict is Verdict.ALLOW
    assert result_for(decision, CheckCode.STRUCTURING).outcome is not Outcome.FAIL


def test_structuring_outranks_the_cap_it_evades():
    # Both the per-payee cap and structuring fail. A human should be told
    # about the evasion, not about the arithmetic.
    mandate = a_mandate(per_payee_limit=usd(100))
    history = [a_charge(usd(60), created_at=ago(60))]
    decision = evaluate(mandate, an_attempt(usd(60)), history)

    assert len(decision.failures) == 2
    assert decision.headline.code is CheckCode.STRUCTURING
    assert "+1 more" in decision.reason()


def test_structuring_is_caught_across_payee_aliases():
    # One merchant, two receiver addresses. Still one merchant.
    directory = PayeeDirectory({"acme_us": "acme", "acme_eu": "acme"})
    history = [a_charge(usd(60), payee="acme_us", created_at=ago(60))]
    decision = evaluate(
        a_mandate(),
        an_attempt(usd(60), payee="acme_eu"),
        history,
        directory=directory,
    )

    failure = result_for(decision, CheckCode.STRUCTURING)
    assert failure.failed
    assert failure.evidence["group"] == "acme"


def test_a_cluster_that_stays_under_the_cap_is_fine():
    history = [a_charge(usd(30), created_at=ago(60))]
    decision = evaluate(a_mandate(), an_attempt(usd(40)), history)

    assert decision.allowed
    assert result_for(decision, CheckCode.STRUCTURING).outcome is Outcome.PASS


def test_charges_older_than_the_window_do_not_form_a_cluster():
    mandate = a_mandate(structuring_window_seconds=900)
    history = [a_charge(usd(60), created_at=ago(1000))]
    decision = evaluate(mandate, an_attempt(usd(60)), history)

    assert decision.allowed


def test_a_released_hold_does_not_form_a_cluster():
    history = [a_charge(usd(60), created_at=ago(60), state=ChargeState.RELEASED)]
    decision = evaluate(a_mandate(), an_attempt(usd(60)), history)

    assert decision.allowed


def test_structuring_confidence_rises_as_amounts_pack_under_the_cap():
    loose = evaluate(
        a_mandate(), an_attempt(usd(60)), [a_charge(usd(60), created_at=ago(60))]
    )
    tight = evaluate(
        a_mandate(), an_attempt(usd(99)), [a_charge(usd(99), created_at=ago(60))]
    )

    assert (
        tight.headline.evidence["confidence"] > loose.headline.evidence["confidence"]
    )


def test_headroom_shrinks_to_what_the_cluster_leaves():
    history = [a_charge(usd(60), created_at=ago(60))]
    decision = evaluate(a_mandate(), an_attempt(usd(60)), history)

    # 100 cap, 60 already clustered, so 40 would still have cleared.
    assert decision.max_allowable == usd(40)


# -- the rest of the taxonomy ---------------------------------------------


def test_per_payee_cap_blocks():
    mandate = a_mandate(per_item_limit=None, per_payee_limit=usd(100))
    history = [a_charge(usd(80), created_at=ago(60))]
    decision = evaluate(mandate, an_attempt(usd(50)), history)

    assert CheckCode.PER_PAYEE_LIMIT in codes(decision)
    assert decision.max_allowable == usd(20)


def test_running_out_of_budget_blocks():
    history = [a_charge(usd(450), payee="other", created_at=ago(60))]
    decision = evaluate(a_mandate(), an_attempt(usd(100)), history)

    assert CheckCode.INSUFFICIENT_BUDGET in codes(decision)
    assert decision.available == usd(50)
    assert decision.max_allowable == usd(50)


def test_too_many_charges_too_fast_blocks():
    mandate = a_mandate(velocity=Velocity(window_seconds=60, max_count=2))
    history = [
        a_charge(usd(10), id="chg_a", payee="one", created_at=ago(30)),
        a_charge(usd(10), id="chg_b", payee="two", created_at=ago(20)),
    ]
    decision = evaluate(mandate, an_attempt(usd(10), payee="three"), history)

    assert CheckCode.VELOCITY in codes(decision)
    assert decision.max_allowable == usd(0)


def test_too_much_money_too_fast_blocks():
    mandate = a_mandate(
        velocity=Velocity(window_seconds=60, max_amount=usd(100)),
    )
    history = [a_charge(usd(60), payee="other", created_at=ago(30))]
    decision = evaluate(mandate, an_attempt(usd(60), payee="another"), history)

    assert CheckCode.VELOCITY in codes(decision)
    assert decision.max_allowable == usd(40)


def test_velocity_ignores_charges_outside_its_window():
    mandate = a_mandate(velocity=Velocity(window_seconds=60, max_count=1))
    history = [a_charge(usd(10), payee="other", created_at=ago(600))]
    decision = evaluate(mandate, an_attempt(usd(10), payee="another"), history)

    assert decision.allowed


def test_concentration_blocks_one_counterparty_taking_the_whole_budget():
    mandate = a_mandate(concentration_max_share=0.5)
    history = [a_charge(usd(100), payee="acme", created_at=ago(600))]
    decision = evaluate(mandate, an_attempt(usd(100), payee="acme"), history)

    failure = result_for(decision, CheckCode.CONCENTRATION)
    assert failure.failed
    assert failure.evidence["share"] == 1.0
    assert decision.max_allowable == usd(0)


def test_concentration_allows_a_spread_book():
    mandate = a_mandate(concentration_max_share=0.5)
    history = [a_charge(usd(100), payee="other", created_at=ago(600))]
    decision = evaluate(mandate, an_attempt(usd(50), payee="acme"), history)

    assert decision.allowed


# -- contract -------------------------------------------------------------


def test_an_attempt_for_another_mandate_is_rejected_outright():
    with pytest.raises(ValueError, match="mnd_other"):
        evaluate(a_mandate(), an_attempt(usd(10), mandate_id="mnd_other"))


def test_history_from_another_mandate_is_ignored():
    history = [a_charge(usd(450), mandate_id="mnd_elsewhere", created_at=ago(60))]
    decision = evaluate(a_mandate(), an_attempt(usd(90)), history)

    assert decision.allowed
    assert decision.available == usd(500)


def test_decisions_serialise_for_the_audit_grid():
    history = [a_charge(usd(60), created_at=ago(60))]
    payload = evaluate(a_mandate(), an_attempt(usd(60)), history).to_dict()

    assert payload["verdict"] == "block"
    assert payload["failed_codes"] == ["structuring"]
    assert len(payload["trace"]) == len(CheckCode)
    assert payload["max_allowable"] == 4000


def test_evaluation_is_deterministic():
    args = (a_mandate(), an_attempt(usd(60)), [a_charge(usd(60), created_at=ago(60))])
    first = evaluate(*args)
    second = evaluate(*args)

    assert first.to_dict() == second.to_dict()
