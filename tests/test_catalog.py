from __future__ import annotations

import json
from decimal import Decimal

import httpx
import pytest
from conftest import usd

from leash.catalog import (
    Channel3Catalog,
    CatalogError,
    Item,
    Offer,
    StaticCatalog,
    build_catalog,
    counterparty_of,
    item_from,
    payee_id_of,
    registrable_domain,
)
from leash.config import Settings
from leash.money import Money


def configured(**overrides) -> Settings:
    return Settings(
        channel3_api_key="test-key",
        channel3_base_url="https://api.trychannel3.test",
        **overrides,
    )


def catalog_with(handler) -> Channel3Catalog:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://api.trychannel3.test",
    )
    return Channel3Catalog(configured(), client=client)


def product(**overrides) -> dict:
    base = {
        "id": "p1",
        "title": "Mesh task chair",
        "brands": [{"id": "b", "name": "Acme"}],
        "category": {"slug": "chairs", "path": [{"slug": "furniture"}, {"slug": "chairs"}]},
        "images": [{"url": "https://img.test/a.jpg", "is_main_image": True}],
        "offers": [
            {
                "domain": "acme.com",
                "price": {"price": 150.00, "currency": "USD"},
                "availability": "InStock",
                "url": "https://acme.com/chair",
            }
        ],
    }
    base.update(overrides)
    return base


def reply(products, status=200) -> httpx.Response:
    return httpx.Response(status, json={"products": products, "next_page_token": None})


# -- merchants are counterparties ----------------------------------------


@pytest.mark.parametrize(
    "host, expected",
    [
        ("nike.com", "nike.com"),
        ("www.nike.com", "nike.com"),
        ("store.nike.com", "nike.com"),
        ("https://shop.acme.co.uk/x", "acme.co.uk"),
        ("eu.acme.co.in", "acme.co.in"),
        ("acme.com:443", "acme.com"),
        ("ACME.COM.", "acme.com"),
    ],
)
def test_hostnames_reduce_to_the_merchant(host, expected):
    assert registrable_domain(host) == expected


def test_two_hostnames_of_one_merchant_are_one_counterparty():
    # This is the alias defence, and with real domains it stops being a
    # scenario built to be caught.
    assert counterparty_of("store.nike.com") == counterparty_of("nike.com") == "nike"
    assert payee_id_of("store.nike.com") == payee_id_of("www.nike.com") == "nike_com"


def test_different_merchants_stay_different():
    assert counterparty_of("acme.com") != counterparty_of("globex.com")


# -- no float ever touches an amount --------------------------------------


async def test_a_json_float_price_becomes_exact_minor_units():
    # The catalogue speaks dollars as JSON numbers. 110.99 in binary floating
    # point is not 110.99, so the amount has to survive the crossing exactly.
    catalog = catalog_with(
        lambda request: reply([product(offers=[{
            "domain": "acme.com",
            "price": {"price": 110.99, "currency": "USD"},
            "availability": "InStock",
        }])])
    )

    items = await catalog.search("chair")

    assert items[0].offers[0].price == Money(11099, "USD")


@pytest.mark.parametrize(
    "raw, minor",
    [
        (0.1, 10),
        (0.07, 7),
        (19.99, 1999),
        (1234.56, 123456),
        ("49.95", 4995),
        (100, 10000),
    ],
)
async def test_awkward_prices_survive_the_crossing(raw, minor):
    catalog = catalog_with(
        lambda request: reply([product(offers=[{
            "domain": "acme.com",
            "price": {"price": raw, "currency": "USD"},
            "availability": "InStock",
        }])])
    )

    items = await catalog.search("chair")

    assert items[0].offers[0].price.minor == minor


def test_parsing_takes_a_decimal_without_rounding_through_a_float():
    item = item_from(product(offers=[{
        "domain": "acme.com",
        "price": {"price": Decimal("0.145"), "currency": "USD"},
        "availability": "InStock",
    }]))

    # Half-up at the currency's precision, the same rule the processor uses.
    assert item is not None
    assert item.offers[0].price == Money(15, "USD")


def test_a_zero_decimal_currency_is_not_given_cents():
    item = item_from(product(offers=[{
        "domain": "acme.co.jp",
        "price": {"price": 4800, "currency": "JPY"},
        "availability": "InStock",
    }]))

    assert item is not None
    assert item.offers[0].price == Money(4800, "JPY")


# -- parsing --------------------------------------------------------------


def test_the_offer_guide_shape_is_accepted_too():
    # The reference calls the field `price`, the offer guide calls it
    # `amount`. Betting on one of them would be a silent breakage.
    item = item_from(product(offers=[{
        "domain": "acme.com",
        "price": {"amount": 42.50, "currency": "USD"},
        "availability": "InStock",
    }]))

    assert item is not None
    assert item.offers[0].price == Money(4250, "USD")


def test_the_broadest_category_is_the_one_a_mandate_scopes_on():
    # A mandate says "furniture", not "chairs".
    item = item_from(product())

    assert item is not None
    assert item.category == "furniture"


async def test_the_offline_catalogue_speaks_the_same_taxonomy_as_the_mandate():
    # The bug this guards against: the offline fixture and the demo mandate
    # drifting onto different category vocabularies, so every offline product
    # reads as out of scope and the engine looks broken while working
    # perfectly. Both sides use Channel3's roots, so both sides agree.
    from leash.store import DEMO_CATEGORIES, OUT_OF_SCOPE_CATEGORIES

    items = await StaticCatalog().search("")
    roots = {item.category for item in items}

    assert roots & DEMO_CATEGORIES, "nothing offline is in scope"
    assert roots - DEMO_CATEGORIES, "nothing offline is out of scope"
    assert roots <= DEMO_CATEGORIES | set(OUT_OF_SCOPE_CATEGORIES), (
        f"offline roots the demo does not account for: "
        f"{roots - DEMO_CATEGORIES - set(OUT_OF_SCOPE_CATEGORIES)}"
    )


def test_a_product_nobody_sells_is_not_a_product():
    assert item_from(product(offers=[])) is None


def test_an_offer_with_an_unreadable_price_is_dropped():
    item = item_from(product(offers=[
        {"domain": "acme.com", "price": {"price": "not a number", "currency": "USD"}},
        {"domain": "globex.com", "price": {"price": 10, "currency": "USD"}},
    ]))

    assert item is not None
    assert [o.domain for o in item.offers] == ["globex.com"]


def test_a_nonsense_currency_is_refused_rather_than_guessed():
    assert item_from(product(offers=[
        {"domain": "acme.com", "price": {"price": 10, "currency": "dollars"}}
    ])) is None


def test_the_main_image_wins_over_the_first_one():
    item = item_from(product(images=[
        {"url": "https://img.test/side.jpg"},
        {"url": "https://img.test/hero.jpg", "is_main_image": True},
    ]))

    assert item is not None
    assert item.image_url == "https://img.test/hero.jpg"


# -- choosing an offer ----------------------------------------------------


def test_the_best_offer_is_the_cheapest_one_in_stock():
    item = item_from(product(offers=[
        {"domain": "acme.com", "price": {"price": 80, "currency": "USD"},
         "availability": "OutOfStock"},
        {"domain": "globex.com", "price": {"price": 95, "currency": "USD"},
         "availability": "InStock"},
        {"domain": "initech.com", "price": {"price": 120, "currency": "USD"},
         "availability": "InStock"},
    ]))

    assert item is not None
    assert item.best is not None
    assert item.best.domain == "globex.com"


def test_a_product_with_nothing_in_stock_has_no_best_offer():
    item = item_from(product(offers=[
        {"domain": "acme.com", "price": {"price": 80, "currency": "USD"},
         "availability": "SoldOut"},
    ]))

    assert item is not None
    assert item.best is None


def test_one_product_can_span_several_counterparties():
    item = item_from(product(offers=[
        {"domain": "acme.com", "price": {"price": 80, "currency": "USD"}},
        {"domain": "eu.acme.com", "price": {"price": 82, "currency": "USD"}},
        {"domain": "globex.com", "price": {"price": 90, "currency": "USD"}},
    ]))

    assert item is not None
    assert item.counterparties == ("acme", "globex")


# -- the request ----------------------------------------------------------


async def test_the_key_goes_in_the_header_not_the_query():
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["key"] = request.headers.get("x-api-key")
        seen["url"] = str(request.url)
        return reply([product()])

    await catalog_with(handler).search("chair")

    assert seen["key"] == "test-key"
    assert "test-key" not in str(seen["url"])


async def test_a_ceiling_becomes_a_price_filter():
    # This is what turns a refusal into a second, cheaper shop.
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content.decode())
        return reply([product()])

    await catalog_with(handler).search("chair", under=usd(100))

    assert seen["body"]["filters"]["price"]["max_price"] == 100
    assert seen["body"]["query"] == "chair"


async def test_a_repeat_search_does_not_spend_another_credit():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return reply([product()])

    catalog = catalog_with(handler)
    await catalog.search("chair")
    await catalog.search("Chair")

    assert calls["n"] == 1


async def test_rate_limiting_says_so_plainly():
    catalog = catalog_with(lambda request: httpx.Response(429, text="slow down"))

    with pytest.raises(CatalogError, match="rate limited"):
        await catalog.search("chair")


async def test_a_refusal_carries_the_status():
    catalog = catalog_with(lambda request: httpx.Response(401, text="bad key"))

    with pytest.raises(CatalogError, match="401"):
        await catalog.search("chair")


async def test_a_response_that_is_not_json_is_an_error():
    catalog = catalog_with(lambda request: httpx.Response(200, text="<html>nope"))

    with pytest.raises(CatalogError):
        await catalog.search("chair")


async def test_a_response_with_no_products_array_is_an_error():
    catalog = catalog_with(lambda request: httpx.Response(200, json={"ok": True}))

    with pytest.raises(CatalogError, match="products"):
        await catalog.search("chair")


async def test_an_unreachable_catalogue_says_so():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    with pytest.raises(CatalogError, match="could not reach"):
        await catalog_with(handler).search("chair")


async def test_no_key_is_refused_before_any_request_goes_out():
    catalog = Channel3Catalog(Settings(channel3_api_key=None))

    with pytest.raises(CatalogError, match="no Channel3 API key"):
        await catalog.search("chair")


# -- the offline catalogue ------------------------------------------------


async def test_the_static_catalogue_needs_no_key_and_no_network():
    items = await StaticCatalog().search("chair")

    assert items
    assert all(isinstance(item, Item) for item in items)
    assert all(isinstance(item.best, Offer) for item in items)


async def test_the_static_catalogue_respects_a_ceiling():
    cheap = await StaticCatalog().search("chair", under=usd(100))

    assert cheap
    assert all(item.best is not None and item.best.price <= usd(100) for item in cheap)


async def test_the_static_catalogue_carries_an_alias_pair():
    # The offline path has to exercise the alias grouping too, or the thing
    # most worth testing is the thing only the live key can reach.
    items = await StaticCatalog().search("desk")

    desk = next(item for item in items if "desk" in item.title.lower())
    assert len(desk.offers) == 2
    assert desk.counterparties == ("northwind",)


async def test_an_unmatched_search_comes_back_empty_rather_than_random():
    assert await StaticCatalog().search("helicopter") == ()


def test_the_build_picks_the_offline_one_without_a_key():
    assert build_catalog(Settings(channel3_api_key=None)).name == "static"


def test_the_build_picks_channel3_with_a_key():
    assert build_catalog(configured()).name == "channel3"
