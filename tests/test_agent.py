from __future__ import annotations

from conftest import NOW, a_mandate, usd

from leash.agent import LineItem, ProcurementAgent, spent
from leash.ledger import Ledger
from leash.models import Velocity


def item(label: str, amount, payee="northwind", category="office") -> LineItem:
    return LineItem(label=label, payee=payee, category=category, amount=amount)


def agent(**overrides) -> tuple[ProcurementAgent, Ledger]:
    ledger = Ledger(a_mandate(allowed_categories=frozenset({"office", "hardware"})))
    return ProcurementAgent(ledger, **overrides), ledger


def test_an_in_scope_list_goes_through():
    buyer, ledger = agent()

    steps = buyer.run([item("paper", usd(40)), item("toner", usd(55))], start=NOW)

    assert [s.action for s in steps] == ["bought", "bought"]
    assert ledger.held == usd(95)


def test_an_over_cap_item_is_trimmed_to_what_would_clear():
    # The decision said 100 would clear, so the agent asks for 100.
    buyer, ledger = agent()

    steps = buyer.run([item("monitor", usd(150))], start=NOW)

    assert steps[0].action == "trimmed"
    assert steps[0].decision.attempt.amount == usd(100)
    assert "asked 150.00 USD, took 100.00 USD" in steps[0].summary()


def test_an_out_of_scope_item_is_abandoned_not_trimmed():
    # No amount fixes being out of scope, so there is nothing to retry with.
    buyer, _ = agent()

    steps = buyer.run([item("laptop", usd(50), category="electronics")], start=NOW)

    assert steps[0].action == "abandoned"
    assert "category_not_allowed" in steps[0].summary()


def test_trimming_can_be_turned_off():
    buyer, ledger = agent(trim_to_allowable=False)

    steps = buyer.run([item("monitor", usd(150))], start=NOW)

    assert steps[0].action == "abandoned"
    assert ledger.held == usd(0)


def test_the_agent_stops_when_the_budget_runs_out():
    buyer, ledger = agent(pace_seconds=120)

    steps = buyer.run(
        [item(f"box {n}", usd(100), payee=f"payee_{n}") for n in range(8)],
        start=NOW,
    )

    assert spent(steps) == 50000
    assert ledger.available == usd(0)
    assert any(s.action == "abandoned" for s in steps)


def test_the_agent_respects_the_pace_limit():
    # Nine charges in the same instant. Each is fine; the burst is not, and no
    # smaller amount fixes it, so there is nothing to trim to.
    ledger = Ledger(a_mandate(velocity=Velocity(window_seconds=60, max_count=4)))
    buyer = ProcurementAgent(ledger)

    steps = buyer.run(
        [item(f"pen {n}", usd(5), payee=f"payee_{n}") for n in range(9)],
        start=NOW,
    )

    abandoned = [s for s in steps if s.action == "abandoned"]
    assert len(abandoned) == 5
    assert all("velocity" in s.summary() for s in abandoned)
    assert ledger.held == usd(20)
