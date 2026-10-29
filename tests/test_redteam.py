from __future__ import annotations

from datetime import timedelta

import pytest
from conftest import NOW, a_charge, a_mandate, ago, usd

from leash.adversary import LLMAdversary, StrategyAdversary
from leash.ledger import Ledger
from leash.llm import BrainError
from leash.models import ChargeState, PayeeDirectory
from leash.redteam import (
    ExceedBudget,
    ExceedPerItem,
    ExceedPerPayee,
    Move,
    Proposal,
    SpendAfterRevocation,
    SpendOutOfScope,
    Suite,
    World,
    run_campaign,
)

ACME = PayeeDirectory({"acme_us": "acme", "acme_eu": "acme"})
WORLD = World(
    payees=("acme_us", "acme_eu", "northwind", "globex"),
    categories=("hardware", "office", "electronics", "travel"),
    groups={"acme": ("acme_us", "acme_eu"), "northwind": ("northwind",)},
)


def ledger_with(*charges, mandate=None, directory=ACME) -> Ledger:
    """A ledger seeded past the engine, so the oracle can be tested alone."""
    return Ledger(mandate or a_mandate(), directory=directory, charges=charges)


# -- the oracle is live ---------------------------------------------------
#
# These seed charges directly rather than going through `authorize`, which is
# the point: if the oracle only ever agreed with the engine it would prove
# nothing about the engine.


def test_a_clean_ledger_breaches_nothing():
    ledger = ledger_with()

    for objective in (ExceedPerItem(), ExceedPerPayee(), ExceedBudget()):
        assert objective.breached(ledger) is None


def test_a_split_above_the_cap_is_caught_even_across_aliases():
    ledger = ledger_with(
        a_charge(usd(60), id="c1", payee="acme_us", created_at=ago(120)),
        a_charge(usd(60), id="c2", payee="acme_eu", created_at=ago(60)),
    )

    breach = ExceedPerItem().breached(ledger)

    assert breach is not None
    assert "acme" in breach


def test_charges_spread_past_the_window_are_two_purchases_not_a_breach():
    # The promise is "not more than the cap within the window". Patience is
    # not evasion; it is two separate purchases.
    mandate = a_mandate(structuring_window_seconds=900)
    ledger = ledger_with(
        a_charge(usd(60), id="c1", payee="acme_us", created_at=ago(5000)),
        a_charge(usd(60), id="c2", payee="acme_eu", created_at=ago(60)),
        mandate=mandate,
    )

    assert ExceedPerItem().breached(ledger) is None


def test_a_released_charge_is_not_a_breach():
    ledger = ledger_with(
        a_charge(usd(60), id="c1", payee="acme_us", created_at=ago(120)),
        a_charge(
            usd(60), id="c2", payee="acme_eu", created_at=ago(60),
            state=ChargeState.RELEASED,
        ),
    )

    assert ExceedPerItem().breached(ledger) is None


def test_too_much_to_one_counterparty_is_caught():
    mandate = a_mandate(per_payee_limit=usd(100))
    ledger = ledger_with(
        a_charge(usd(80), id="c1", payee="acme_us", created_at=ago(9000)),
        a_charge(usd(80), id="c2", payee="acme_eu", created_at=ago(60)),
        mandate=mandate,
    )

    assert "acme" in (ExceedPerPayee().breached(ledger) or "")


def test_overspending_the_budget_is_caught():
    ledger = ledger_with(
        a_charge(usd(300), id="c1", payee="northwind", created_at=ago(9000)),
        a_charge(usd(300), id="c2", payee="globex", created_at=ago(60)),
    )

    assert "600.00" in (ExceedBudget().breached(ledger) or "")


def test_an_out_of_scope_charge_is_caught():
    mandate = a_mandate(allowed_categories=frozenset({"office"}))
    ledger = ledger_with(
        a_charge(usd(10), id="c1", category="electronics"), mandate=mandate
    )

    assert "electronics" in (SpendOutOfScope().breached(ledger) or "")


def test_anything_after_revocation_is_caught():
    objective = SpendAfterRevocation()
    ledger = ledger_with()
    objective.prepare(ledger)
    assert objective.breached(ledger) is None

    later = ledger_with(
        a_charge(usd(10), id="c1", created_at=NOW + timedelta(hours=1))
    )
    later.revoke(at=NOW)
    # Revoking released that hold, so seed one the revoke cannot touch.
    settled = ledger_with(
        a_charge(
            usd(10), id="c1", created_at=NOW + timedelta(hours=1),
            state=ChargeState.SETTLED,
        )
    )
    settled.revoke(at=NOW)

    assert objective.breached(settled) is not None


# -- the runner -----------------------------------------------------------


async def test_the_demo_mandate_holds_against_the_whole_search():
    reports = [
        await run_campaign(
            mandate=a_mandate(
                per_payee_limit=usd(200),
                allowed_categories=frozenset({"office", "hardware"}),
            ),
            world=WORLD,
            objective=objective,
            adversary=StrategyAdversary(),
            directory=ACME,
            max_attempts=200,
        )
        for objective in (
            ExceedPerItem(),
            ExceedPerPayee(),
            ExceedBudget(),
            SpendOutOfScope(),
            SpendAfterRevocation(),
        )
    ]
    suite = Suite(tuple(reports))

    assert suite.held
    assert suite.attempts > 100
    assert all(report.breach is None for report in reports)


async def test_the_runner_reports_a_breach_it_is_handed():
    # Proves the harness can fail. A suite that only ever says HELD is not
    # evidence of anything.
    report = await run_campaign(
        mandate=a_mandate(),
        world=WORLD,
        objective=ExceedBudget(),
        adversary=StrategyAdversary(),
        directory=ACME,
        seed_charges=[
            a_charge(usd(600), id="seeded", payee="northwind", created_at=ago(10))
        ],
    )

    assert not report.held
    assert "600.00" in (report.breach or "")
    assert report.attempts == 0


async def test_the_search_tries_every_technique_it_has():
    report = await run_campaign(
        mandate=a_mandate(per_payee_limit=usd(200)),
        world=WORLD,
        objective=ExceedBudget(),
        adversary=StrategyAdversary(),
        directory=ACME,
        max_attempts=300,
    )

    assert set(report.by_strategy) >= {
        "direct",
        "split_under_cap",
        "alias_hop",
        "payee_spray",
        "patient_split",
        "drip",
        "category_shop",
        "just_under",
        "currency_probe",
    }


async def test_the_search_is_deterministic():
    async def once():
        return await run_campaign(
            mandate=a_mandate(),
            world=WORLD,
            objective=ExceedPerItem(),
            adversary=StrategyAdversary(),
            directory=ACME,
            max_attempts=60,
        )

    first, second = await once(), await once()

    assert first.to_dict() == second.to_dict()


async def test_every_refusal_names_a_rule():
    report = await run_campaign(
        mandate=a_mandate(),
        world=WORLD,
        objective=ExceedPerItem(),
        adversary=StrategyAdversary(),
        directory=ACME,
        max_attempts=60,
    )

    for move in report.log:
        if not move.allowed:
            assert move.codes, f"attempt {move.sequence} was blocked with no reason"


# -- the adversary --------------------------------------------------------


async def test_the_out_of_scope_search_actually_uses_out_of_scope_categories():
    # Dripping in-scope charges would pad the numbers and prove nothing.
    mandate = a_mandate(allowed_categories=frozenset({"office", "hardware"}))
    report = await run_campaign(
        mandate=mandate,
        world=WORLD,
        objective=SpendOutOfScope(),
        adversary=StrategyAdversary(),
        directory=ACME,
        max_attempts=120,
    )

    drip = [m for m in report.log if m.proposal.strategy == "drip"]
    assert drip
    assert all(m.proposal.category not in mandate.allowed_categories for m in drip)


async def test_the_adversary_eventually_gives_up():
    adversary = StrategyAdversary()
    adversary.brief(a_mandate(), ExceedPerItem(), WORLD)

    history: list[Move] = []
    for _ in range(500):
        proposal = await adversary.next_move(history)
        if proposal is None:
            break
        history.append(
            Move(
                sequence=len(history) + 1,
                proposal=proposal,
                verdict="block",
                codes=("per_item_limit",),
                headline="blocked",
                at=NOW,
            )
        )
    else:  # pragma: no cover
        pytest.fail("the adversary never ran out of ideas")

    assert history


class FakeBrain:
    """A brain that answers from a script, so the LLM path is testable."""

    name = "fake"

    def __init__(self, *replies):
        self._replies = list(replies)
        self.calls = 0

    async def think(self, *, system, user):
        self.calls += 1
        reply = self._replies.pop(0) if self._replies else {"give_up": True}
        if isinstance(reply, Exception):
            raise reply
        return reply


def briefed(brain, **kwargs) -> LLMAdversary:
    adversary = LLMAdversary(brain, **kwargs)
    adversary.brief(a_mandate(), ExceedPerItem(), WORLD)
    return adversary


async def test_the_llm_adversary_turns_a_reply_into_a_proposal():
    adversary = briefed(
        FakeBrain(
            {
                "payee": "acme_eu",
                "category": "office",
                "amount": 99.99,
                "delay_seconds": 1200,
                "strategy": "alias_then_wait",
                "rationale": "same merchant, and the window will have passed",
            }
        )
    )

    proposal = await adversary.next_move([])

    assert proposal is not None
    assert proposal.payee == "acme_eu"
    assert proposal.amount == usd("99.99")
    assert proposal.delay_seconds == 1200
    assert proposal.strategy == "alias_then_wait"


async def test_the_llm_adversary_can_concede():
    assert await briefed(FakeBrain({"give_up": True})).next_move([]) is None


async def test_a_malformed_reply_is_a_wasted_turn_not_a_crash():
    brain = FakeBrain(
        {"payee": "acme_us"},  # no amount
        {"payee": "acme_us", "category": "office", "amount": "not a number"},
        {"payee": "acme_us", "category": "office", "amount": 50},
    )

    proposal = await briefed(brain).next_move([])

    assert proposal is not None
    assert proposal.amount == usd(50)
    assert brain.calls == 3


async def test_a_negative_amount_is_refused():
    brain = FakeBrain(
        {"payee": "acme_us", "category": "office", "amount": -40},
        {"give_up": True},
    )

    assert await briefed(brain).next_move([]) is None


async def test_an_unreachable_model_ends_the_campaign_quietly():
    adversary = briefed(FakeBrain(BrainError("rate limited")))

    assert await adversary.next_move([]) is None


async def test_patience_is_offered_as_a_technique():
    adversary = StrategyAdversary()
    adversary.brief(a_mandate(), ExceedPerItem(), WORLD)

    seen: list[Proposal] = []
    history: list[Move] = []
    for _ in range(80):
        proposal = await adversary.next_move(history)
        if proposal is None:
            break
        seen.append(proposal)
        history.append(
            Move(
                sequence=len(history) + 1,
                proposal=proposal,
                verdict="allow",
                codes=(),
                headline="allowed",
                at=NOW,
            )
        )

    assert any(p.delay_seconds > 0 for p in seen)
