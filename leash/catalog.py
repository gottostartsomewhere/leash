"""The things an agent can actually buy.

Channel3 is a real product catalog: real titles, real merchants, real prices.
That matters here for a reason beyond decoration. A mandate's whole job is to
bound spending against counterparties, and until now the counterparties were
five names I made up. Real merchant domains make two of the engine's defences
non-contrived at once:

- A product usually carries several offers from different domains, so the agent
  genuinely chooses who to pay rather than being handed one payee.
- Merchants really do sell under more than one hostname, so grouping
  `store.nike.com` with `nike.com` is a real alias problem rather than a
  scenario built to be caught.

One wrinkle worth being explicit about. Channel3 returns prices as JSON
numbers in dollars and cents, and this codebase's first rule is that no float
ever touches an amount. So the response is parsed with `parse_float=Decimal`
and the value reaches `Money.from_major` as a Decimal. A float of 110.99 never
exists at any point, not even briefly.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Final, Iterable, Mapping, Protocol, Sequence

import httpx

from .config import Settings, settings as default_settings
from .money import Money

# -- merchants ------------------------------------------------------------

# Enough of the public suffix list to be right about the domains a catalogue
# actually returns. A full PSL is a dependency and a download; this is a
# documented heuristic, and `counterparty_of` is the one place it is wrong.
_COMPOUND_SUFFIXES: Final[frozenset[str]] = frozenset(
    {
        "co.uk", "org.uk", "me.uk", "ac.uk", "gov.uk",
        "co.in", "net.in", "org.in",
        "com.au", "net.au", "org.au",
        "co.nz", "co.za", "co.jp", "or.jp", "ne.jp",
        "com.br", "com.mx", "com.sg", "com.hk", "com.tr",
    }
)


def registrable_domain(host: str) -> str:
    """`store.nike.com` and `www.nike.com` both reduce to `nike.com`."""
    cleaned = host.strip().lower().rstrip(".")
    if cleaned.startswith("http://") or cleaned.startswith("https://"):
        cleaned = cleaned.split("//", 1)[1]
    cleaned = cleaned.split("/", 1)[0].split(":", 1)[0]
    labels = [label for label in cleaned.split(".") if label]
    if len(labels) <= 2:
        return ".".join(labels)
    if ".".join(labels[-2:]) in _COMPOUND_SUFFIXES:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def counterparty_of(domain: str) -> str:
    """The payee group for a merchant: `nike.com` becomes `nike`.

    This is what makes the alias defence real. Two offers on different
    hostnames of one merchant are one counterparty, and the per-counterparty
    cap and the structuring window both measure against this, not the URL.
    """
    registrable = registrable_domain(domain)
    return registrable.split(".", 1)[0] if registrable else domain.lower()


def payee_id_of(domain: str) -> str:
    """A stable payee id for a merchant hostname."""
    return registrable_domain(domain).replace(".", "_") or domain.lower()


# -- what comes back ------------------------------------------------------

#: Channel3's reference documents InStock and OutOfStock; its search filters
#: name several more. Anything not explicitly unavailable is treated as
#: buyable, and the raw string is kept so the screen can say which it was.
_UNAVAILABLE: Final[frozenset[str]] = frozenset(
    {"outofstock", "soldout", "discontinued"}
)


@dataclass(frozen=True, slots=True)
class Offer:
    """One merchant's price for one product."""

    domain: str
    price: Money
    availability: str = "InStock"
    url: str = ""
    condition: str | None = None

    @property
    def payee(self) -> str:
        return payee_id_of(self.domain)

    @property
    def counterparty(self) -> str:
        return counterparty_of(self.domain)

    @property
    def in_stock(self) -> bool:
        return self.availability.replace(" ", "").lower() not in _UNAVAILABLE

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "payee": self.payee,
            "counterparty": self.counterparty,
            "amount": self.price.minor,
            "currency": self.price.currency,
            "display": str(self.price),
            "availability": self.availability,
            "in_stock": self.in_stock,
            "url": self.url,
            "condition": self.condition,
        }


@dataclass(frozen=True, slots=True)
class Item:
    """A product, with every merchant selling it."""

    id: str
    title: str
    offers: tuple[Offer, ...]
    brand: str = ""
    category: str = ""
    image_url: str = ""

    @property
    def best(self) -> Offer | None:
        """The cheapest offer that is actually in stock."""
        live = [offer for offer in self.offers if offer.in_stock]
        if not live:
            return None
        return min(live, key=lambda offer: offer.price.minor)

    @property
    def counterparties(self) -> tuple[str, ...]:
        seen: dict[str, None] = {}
        for offer in self.offers:
            seen.setdefault(offer.counterparty, None)
        return tuple(seen)

    def to_dict(self) -> dict[str, Any]:
        best = self.best
        return {
            "id": self.id,
            "title": self.title,
            "brand": self.brand,
            "category": self.category,
            "image_url": self.image_url,
            "offers": [offer.to_dict() for offer in self.offers],
            "best": best.to_dict() if best else None,
            "counterparties": list(self.counterparties),
        }


class CatalogError(RuntimeError):
    """The catalogue could not be reached or did not make sense."""


class Catalog(Protocol):
    name: str

    async def search(
        self, query: str, *, under: Money | None = None, limit: int = 8
    ) -> tuple[Item, ...]: ...


# -- parsing --------------------------------------------------------------


def _decimal(value: Any) -> Decimal | None:
    """Everything numeric arrives as Decimal or str. Never as float."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        try:
            return Decimal(value.strip())
        except InvalidOperation:
            return None
    if isinstance(value, float):
        # Only reachable if a caller hands us a dict it parsed itself. str()
        # first, because Decimal(0.1) is not 0.1.
        return Decimal(str(value))
    return None


def _price_of(raw: Mapping[str, Any]) -> Money | None:
    """Read a price, tolerating both shapes Channel3's docs show.

    The API reference calls the field `price`; the offer guide calls it
    `amount`. Rather than bet on one, accept either and fail closed if
    neither is a number we can represent exactly.
    """
    currency = str(raw.get("currency") or "USD").upper()
    if len(currency) != 3 or not currency.isalpha():
        return None
    for key in ("price", "amount", "value"):
        amount = _decimal(raw.get(key))
        if amount is not None and amount >= 0:
            return Money.from_major(amount, currency)
    return None


def _offer_from(raw: Mapping[str, Any]) -> Offer | None:
    domain = str(raw.get("domain") or "").strip()
    price_block = raw.get("price")
    if not domain or not isinstance(price_block, Mapping):
        return None
    price = _price_of(price_block)
    if price is None:
        return None
    return Offer(
        domain=domain,
        price=price,
        availability=str(raw.get("availability") or "InStock"),
        url=str(raw.get("url") or ""),
        condition=(str(raw["condition"]) if raw.get("condition") else None),
    )


def _category_of(raw: Mapping[str, Any]) -> str:
    """The broadest category the catalogue gives, which is what a mandate scopes on.

    A mandate says "office supplies"; it does not say "ballpoint pens". So the
    root of the category path is the useful one, and the leaf is noise here.
    """
    block = raw.get("category")
    if not isinstance(block, Mapping):
        return ""
    path = block.get("path")
    if isinstance(path, Sequence) and not isinstance(path, (str, bytes)):
        for step in path:
            if isinstance(step, Mapping) and step.get("slug"):
                return str(step["slug"])
    return str(block.get("slug") or "")


def _image_of(raw: Mapping[str, Any]) -> str:
    images = raw.get("images")
    if not isinstance(images, Sequence) or isinstance(images, (str, bytes)):
        return ""
    best = ""
    for image in images:
        if not isinstance(image, Mapping):
            continue
        url = str(image.get("cleaned_url") or image.get("url") or "")
        if not url:
            continue
        if image.get("is_main_image"):
            return url
        best = best or url
    return best


def _brand_of(raw: Mapping[str, Any]) -> str:
    brands = raw.get("brands")
    if isinstance(brands, Sequence) and not isinstance(brands, (str, bytes)):
        for brand in brands:
            if isinstance(brand, Mapping) and brand.get("name"):
                return str(brand["name"])
    return ""


def item_from(raw: Mapping[str, Any]) -> Item | None:
    """Build an Item from one Channel3 product, or None if it is unusable."""
    product_id = str(raw.get("id") or "").strip()
    title = str(raw.get("title") or "").strip()
    if not product_id or not title:
        return None

    offers_raw = raw.get("offers")
    offers: list[Offer] = []
    if isinstance(offers_raw, Sequence) and not isinstance(offers_raw, (str, bytes)):
        for entry in offers_raw:
            if isinstance(entry, Mapping):
                offer = _offer_from(entry)
                if offer is not None:
                    offers.append(offer)
    if not offers:
        # A product nobody sells cannot be bought, so it is not a product.
        return None

    return Item(
        id=product_id,
        title=title,
        offers=tuple(offers),
        brand=_brand_of(raw),
        category=_category_of(raw),
        image_url=_image_of(raw),
    )


# -- the real one ---------------------------------------------------------


@dataclass
class _Cached:
    items: tuple[Item, ...]
    at: float


class Channel3Catalog:
    """Channel3's `POST /v1/search`.

    Cached on purpose. A search costs a credit against a monthly free
    allowance, and a demo that re-queries on every reload would burn the
    allowance proving nothing.
    """

    name = "channel3"

    def __init__(self, config: Settings | None = None, client: httpx.AsyncClient | None = None):
        self._config = config or default_settings()
        self._client = client or httpx.AsyncClient(
            base_url=self._config.channel3_base_url,
            timeout=self._config.request_timeout_seconds,
        )
        self._cache: dict[tuple[str, int | None, int], _Cached] = {}

    def _headers(self) -> dict[str, str]:
        key = self._config.channel3_api_key
        if not key:
            raise CatalogError("no Channel3 API key configured")
        return {"x-api-key": key, "content-type": "application/json"}

    async def search(
        self, query: str, *, under: Money | None = None, limit: int = 8
    ) -> tuple[Item, ...]:
        cache_key = (query.strip().lower(), under.minor if under else None, limit)
        hit = self._cache.get(cache_key)
        if hit and (time.monotonic() - hit.at) < self._config.channel3_cache_seconds:
            return hit.items

        body: dict[str, Any] = {"query": query, "limit": limit}
        if under is not None:
            # The filter is in major units, which is the one place this
            # codebase hands a decimal number back out to the world.
            body["filters"] = {"price": {"max_price": float(under.major)}}

        try:
            response = await self._client.post(
                "/v1/search", json=body, headers=self._headers()
            )
        except httpx.HTTPError as exc:
            raise CatalogError(f"could not reach Channel3: {exc}") from exc

        if response.status_code == 429:
            raise CatalogError("rate limited by Channel3, retry in a few seconds")
        if response.status_code >= 400:
            raise CatalogError(
                f"Channel3 refused the search ({response.status_code}): {response.text[:200]}"
            )

        # parse_float=Decimal is the whole point: prices arrive as JSON numbers
        # in dollars, and a float of 110.99 must never exist even briefly.
        try:
            payload = json.loads(response.text, parse_float=Decimal)
        except ValueError as exc:
            raise CatalogError("Channel3 returned something that was not JSON") from exc
        if not isinstance(payload, Mapping):
            raise CatalogError("Channel3 returned a response with no object at the top")

        raw_products = payload.get("products")
        if not isinstance(raw_products, Sequence) or isinstance(raw_products, (str, bytes)):
            raise CatalogError("Channel3 returned no products array")

        items = tuple(
            item
            for item in (
                item_from(entry) for entry in raw_products if isinstance(entry, Mapping)
            )
            if item is not None
        )
        self._cache[cache_key] = _Cached(items=items, at=time.monotonic())
        return items

    async def aclose(self) -> None:
        await self._client.aclose()


# -- the offline one ------------------------------------------------------

#: Shaped exactly like Channel3's own responses, down to the taxonomy: these
#: are real Google Product Taxonomy roots, the same ones a live search
#: returns, so a mandate scoped to `furniture` and `office-supplies` behaves
#: identically whether or not a key is set. Includes two hostnames for one
#: merchant, so the offline path exercises the alias grouping too.
_STATIC: Final[tuple[Mapping[str, Any], ...]] = (
    {
        "id": "stat_desk_01",
        "title": "Sit-stand desk, 140cm, oak",
        "brands": [{"id": "b1", "name": "Northwind"}],
        "category": {"slug": "desks", "path": [{"slug": "furniture"}, {"slug": "desks"}]},
        "images": [{"url": "", "is_main_image": True}],
        "offers": [
            {"domain": "northwind.com", "price": {"price": Decimal("249.00"), "currency": "USD"},
             "availability": "InStock", "url": "https://northwind.com/desk"},
            {"domain": "shop.northwind.com", "price": {"price": Decimal("239.50"), "currency": "USD"},
             "availability": "InStock", "url": "https://shop.northwind.com/desk"},
        ],
    },
    {
        "id": "stat_chair_01",
        "title": "Mesh task chair, adjustable arms",
        "brands": [{"id": "b2", "name": "Acme"}],
        "category": {"slug": "chairs", "path": [{"slug": "furniture"}, {"slug": "chairs"}]},
        "offers": [
            {"domain": "acme.com", "price": {"price": Decimal("150.00"), "currency": "USD"},
             "availability": "InStock", "url": "https://acme.com/chair"},
            {"domain": "eu.acme.com", "price": {"price": Decimal("152.00"), "currency": "USD"},
             "availability": "InStock", "url": "https://eu.acme.com/chair"},
        ],
    },
    {
        "id": "stat_chair_02",
        "title": "Mesh task chair, fixed arms",
        "brands": [{"id": "b2", "name": "Acme"}],
        "category": {"slug": "chairs", "path": [{"slug": "furniture"}, {"slug": "chairs"}]},
        "offers": [
            {"domain": "acme.com", "price": {"price": Decimal("88.00"), "currency": "USD"},
             "availability": "InStock", "url": "https://acme.com/chair-fixed"},
        ],
    },
    {
        "id": "stat_paper_01",
        "title": "A4 copier paper, 5 reams",
        "brands": [{"id": "b1", "name": "Northwind"}],
        "category": {
            "slug": "paper", "path": [{"slug": "office-supplies"}, {"slug": "paper"}]
        },
        "offers": [
            # The cheaper listing is out of stock, so picking on price alone
            # would buy something nobody can ship.
            {"domain": "northwind.com", "price": {"price": Decimal("34.00"), "currency": "USD"},
             "availability": "OutOfStock", "url": "https://northwind.com/paper-bulk"},
            {"domain": "northwind.com", "price": {"price": Decimal("38.00"), "currency": "USD"},
             "availability": "InStock", "url": "https://northwind.com/paper"},
        ],
    },
    {
        "id": "stat_pens_01",
        "title": "Ballpoint pens, box of 50",
        "brands": [{"id": "b1", "name": "Northwind"}],
        "category": {
            "slug": "pens", "path": [{"slug": "office-supplies"}, {"slug": "pens"}]
        },
        "offers": [
            {"domain": "northwind.com", "price": {"price": Decimal("12.40"), "currency": "USD"},
             "availability": "InStock", "url": "https://northwind.com/pens"},
        ],
    },
    {
        "id": "stat_monitor_01",
        "title": "27-inch 4K monitor",
        "brands": [{"id": "b3", "name": "Globex"}],
        "category": {
            "slug": "monitors", "path": [{"slug": "electronics"}, {"slug": "monitors"}]
        },
        "offers": [
            {"domain": "globex.com", "price": {"price": Decimal("319.99"), "currency": "USD"},
             "availability": "InStock", "url": "https://globex.com/monitor"},
        ],
    },
    {
        "id": "stat_speaker_01",
        "title": "Bluetooth speaker, portable",
        "brands": [{"id": "b4", "name": "Initech"}],
        "category": {
            "slug": "audio", "path": [{"slug": "electronics"}, {"slug": "audio"}]
        },
        "offers": [
            {"domain": "initech.com", "price": {"price": Decimal("59.00"), "currency": "USD"},
             "availability": "InStock", "url": "https://initech.com/speaker"},
        ],
    },
    {
        "id": "stat_lamp_01",
        "title": "Desk lamp, warm LED",
        "brands": [{"id": "b4", "name": "Initech"}],
        "category": {
            "slug": "lighting", "path": [{"slug": "home-garden"}, {"slug": "lighting"}]
        },
        "offers": [
            {"domain": "initech.com", "price": {"price": Decimal("44.00"), "currency": "USD"},
             "availability": "InStock", "url": "https://initech.com/lamp"},
        ],
    },
)


class StaticCatalog:
    """A fixed catalogue with no network, so tests and the demo run anywhere.

    Not a mock of Channel3's transport but of its *data*: the same shapes go
    through the same `item_from`, so the parsing is exercised either way.
    """

    name = "static"

    def __init__(self, raw: Iterable[Mapping[str, Any]] = _STATIC):
        self._items = tuple(
            item for item in (item_from(entry) for entry in raw) if item is not None
        )

    async def search(
        self, query: str, *, under: Money | None = None, limit: int = 8
    ) -> tuple[Item, ...]:
        words = [word for word in query.lower().split() if word]
        found: list[tuple[int, Item]] = []
        for item in self._items:
            haystack = f"{item.title} {item.brand} {item.category}".lower()
            score = sum(1 for word in words if word in haystack)
            if words and score == 0:
                continue
            best = item.best
            # A price in another currency is not comparable, so it is not
            # filtered out here. The engine refuses it with currency_mismatch,
            # which is the right place for that judgement to be made.
            if (
                under is not None
                and best is not None
                and best.price.currency == under.currency
                and best.price > under
            ):
                continue
            found.append((-score, item))
        found.sort(key=lambda pair: (pair[0], pair[1].id))
        return tuple(item for _, item in found[:limit])


def build_catalog(config: Settings | None = None) -> Catalog:
    """Channel3 when a key is set, the static catalogue when not."""
    config = config or default_settings()
    if config.channel3_configured:
        return Channel3Catalog(config)
    return StaticCatalog()
