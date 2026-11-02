from __future__ import annotations

from conftest import NOW, a_mandate, usd

from leash.agent import Need, ShoppingAgent, bought
from leash.catalog import CatalogError, StaticCatalog
from leash.ledger import Ledger
from leash.models import PayeeDirectory, Velocity

# The real taxonomy roots the catalogue classifies against, so the mandate
# and the shop agree whether or not a Channel3 key is set.
OFFICE = frozenset({"office-supplies", "furniture"})


def shopper(catalog=None, mandate=None, **kwargs):
    ledger = Ledger(
        mandate or a_mandate(allowed_categories=OFFICE),
        directory=PayeeDirectory(),
    )
    return ShoppingAgent(ledger, catalog or StaticCatalog(), **kwargs), ledger


def codes(decision) -> list[str]:
    return [result.code.value for result in decision.failures]


class Empty:
    name = "empty"

    async def search(self, query, *, under=None, limit=8):
        return ()


class Broken:
    name = "broken"

    def __init__(self, fail_on=1):
        self.calls = 0
        self._fail_on = fail_on

    async def search(self, query, *, under=None, limit=8):
        self.calls += 1
        if self.calls >= self._fail_on:
            raise CatalogError("could not reach Channel3: no route")
        return await StaticCatalog().search(query, under=under, limit=limit)


# -- the ordinary case ----------------------------------------------------


async def test_it_buys_the_best_match_it_can_afford():
    agent, ledger = shopper()

    steps = await agent.run([Need("paper")], start=NOW)

    assert steps[0].action == "bought"
    assert steps[0].item is not None
    assert "paper" in steps[0].item.title.lower()
    assert ledger.held == usd("38.00")


async def test_it_pays_the_cheapest_merchant_for_the_same_product():
    # The desk is listed twice by one merchant. Same desk, so take the
    # cheaper listing. A cap that lets the desk through, or this is really a
    # test about reshopping.
    agent, _ = shopper(mandate=a_mandate(
        per_item_limit=usd(500), allowed_categories=OFFICE
    ))

    steps = await agent.run([Need("desk")], start=NOW)

    assert steps[0].action == "bought"
    assert steps[0].offer is not None
    assert steps[0].offer.domain == "shop.northwind.com"
    assert steps[0].offer.price == usd("239.50")


async def test_two_hostnames_of_one_merchant_become_one_payee():
    # shop.northwind.com and northwind.com are one counterparty, so the
    # per-counterparty cap and the structuring window both see one merchant.
    agent, ledger = shopper(mandate=a_mandate(
        per_item_limit=usd(500), allowed_categories=OFFICE
    ))

    await agent.run([Need("desk"), Need("paper")], start=NOW)

    assert {c.payee for c in ledger.charges()} == {"northwind_com"}


# -- the counter-offer becomes the next search ----------------------------


async def test_a_refusal_sends_it_back_to_the_shop_with_a_ceiling():
    # This is the whole reason the catalogue is here. The top chair is 150
    # against a 100 cap, so it reshops under 100 and buys the 88 one.
    agent, ledger = shopper()

    steps = await agent.run([Need("chair")], start=NOW)
    step = steps[0]

    assert step.action == "reshopped"
    assert step.first_choice is not None
    assert step.first_choice.offers[0].price == usd("150.00")
    assert step.ceiling == usd("100.00")
    assert step.offer is not None
    assert step.offer.price == usd("88.00")
    assert ledger.held == usd("88.00")


async def test_the_reshop_is_reported_in_words_a_person_can_read():
    agent, _ = shopper()

    steps = await agent.run([Need("chair")], start=NOW)

    summary = steps[0].summary()
    assert "was refused" in summary
    assert "88.00 USD" in summary


async def test_reshopping_can_be_turned_off():
    agent, ledger = shopper(reshop=False)

    steps = await agent.run([Need("chair")], start=NOW)

    assert steps[0].action == "refused"
    assert ledger.held == usd(0)


async def test_it_gives_up_when_nothing_cheap_enough_exists():
    # The cheapest desk is 239.50 and the cap is 50, so the second search
    # comes back empty and there is nothing left to try.
    agent, ledger = shopper(mandate=a_mandate(
        per_item_limit=usd(50), allowed_categories=OFFICE
    ))

    # "desk" alone would also match the desk lamp, which is out of scope, so
    # this asks for the one thing only the desk matches.
    steps = await agent.run([Need("sit-stand")], start=NOW)

    assert steps[0].action == "refused"
    assert "nothing under" in steps[0].detail
    assert ledger.held == usd(0)


async def test_an_out_of_scope_category_is_not_fixed_by_shopping_cheaper():
    # The speaker is electronics. No price makes it in scope, and the agent
    # should not burn a second search finding that out.
    agent, ledger = shopper()

    steps = await agent.run([Need("speaker")], start=NOW)

    assert steps[0].action == "refused"
    assert steps[0].decision is not None
    assert "category_not_allowed" in codes(steps[0].decision)
    assert ledger.held == usd(0)


# -- stock ----------------------------------------------------------------


async def test_it_will_not_buy_something_that_is_out_of_stock():
    # Paper has a cheaper listing at 34.00 that nobody can ship. Picking on
    # price alone would take it.
    agent, ledger = shopper()

    steps = await agent.run([Need("paper")], start=NOW)

    assert steps[0].offer is not None
    assert steps[0].offer.in_stock
    assert steps[0].offer.price == usd("38.00")
    assert ledger.held == usd("38.00")


# -- the catalogue failing ------------------------------------------------


async def test_nothing_found_is_not_a_crash():
    agent, _ = shopper(Empty())

    steps = await agent.run([Need("helicopter")], start=NOW)

    assert steps[0].action == "nothing_found"
    assert "nothing in the catalogue" in steps[0].summary()


async def test_an_unreachable_catalogue_is_reported_not_raised():
    agent, _ = shopper(Broken(fail_on=1))

    steps = await agent.run([Need("chair")], start=NOW)

    assert steps[0].action == "unreachable"
    assert "could not reach" in steps[0].summary()


async def test_the_catalogue_dying_mid_reshop_keeps_the_first_refusal():
    # First search works and is refused; the second one fails. The agent
    # should still be able to say what happened.
    agent, ledger = shopper(Broken(fail_on=2))

    steps = await agent.run([Need("chair")], start=NOW)

    assert steps[0].action == "unreachable"
    assert steps[0].decision is not None
    assert not steps[0].decision.allowed
    assert ledger.held == usd(0)


# -- several needs --------------------------------------------------------


async def test_it_works_a_list_and_stops_when_the_budget_is_gone():
    agent, ledger = shopper(mandate=a_mandate(
        total_limit=usd(150), per_item_limit=usd(100), allowed_categories=OFFICE
    ))

    steps = await agent.run(
        [Need("paper"), Need("chair"), Need("pens")], start=NOW
    )

    assert bought(steps) == ledger.held.minor
    assert ledger.held <= usd(150)


async def test_the_pace_limit_is_reported_rather_than_worked_around():
    agent, _ = shopper(
        mandate=a_mandate(
            velocity=Velocity(window_seconds=60, max_count=1),
            allowed_categories=OFFICE,
        ),
    )

    steps = await agent.run([Need("paper"), Need("pens")], start=NOW)

    assert steps[0].action == "bought"
    assert steps[1].action == "refused"
    assert steps[1].decision is not None
    assert "velocity" in codes(steps[1].decision)
