"""Put any agent on a Leash.

An MCP endpoint, so that an agent which is not ours, a Claude or a ChatGPT
or anything else that speaks the Model Context Protocol, can read the
mandate, shop the live catalogue and ask to spend, through the same eleven
checks, into the same audit grid the screen shows.

The built-in shopping agent was only ever a demonstration of the thing that
matters, which is the layer between an agent and the money. That layer is
more useful the less it cares whose agent is on the other side of it.

What is not here is deliberate. There is no tool that moves money. An
allowed purchase is a hold, and holds are released by a person, on the
screen, not by the agent that asked. There is no tool that revokes, widens
or edits the mandate either. The agent gets exactly the authority it would
get over HTTP, which is to ask.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, AsyncIterator, Callable

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import Field
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .catalog import Catalog, CatalogError
from .config import Settings
from .ledger import Ledger
from .models import Attempt, Mandate
from .money import Money
from .store import DEMO_MANDATE_ID, Store, register_merchants

INSTRUCTIONS = """\
Leash holds a spending mandate on behalf of a person. Through these tools you \
can read that mandate, search a live product catalogue, and ask to spend.

You cannot move money. An allowed purchase becomes a hold against the budget, \
and only the person releases held charges, from the Leash screen. Every \
request is checked against eleven rules before anything is held.

When a request is refused, the result names every rule that refused it and \
the largest amount that would have cleared. Use that to choose something \
else rather than retrying the same request. Splitting one purchase into \
smaller ones to get under a cap is recognised as structuring and refused, \
even across a merchant's different addresses.

Typical flow: read_mandate, then search_products, then request_purchase with \
the payee and category from a search result.\
"""

_READ = ToolAnnotations(readOnlyHint=True, openWorldHint=False)


def _money(m: Money | None) -> str | None:
    return None if m is None else str(m)


def _terms(mandate: Mandate) -> dict[str, Any]:
    """The mandate in words a model reads well: money as "100.00 USD"."""
    velocity = mandate.velocity
    return {
        "total": _money(mandate.total_limit),
        "per_purchase": _money(mandate.per_item_limit),
        "per_merchant": _money(mandate.per_payee_limit),
        "categories": sorted(mandate.allowed_categories) if mandate.allowed_categories else "any",
        "merchants": sorted(mandate.allowed_payees) if mandate.allowed_payees else "any known merchant",
        "pace": None
        if velocity is None
        else {
            "window_seconds": velocity.window_seconds,
            "max_purchases": velocity.max_count,
            "max_amount": _money(velocity.max_amount),
        },
        "split_purchases_grouped_within_seconds": mandate.structuring_window_seconds,
        "expires": mandate.ends_at.isoformat(),
    }


def _major(minor: int | None, currency: str) -> str | None:
    """Minor units as "100.00 USD".

    The decision payload carries money as integer minor units, which is
    right for a ledger and wrong for a model. Handed raw, "largest that would
    clear: 10000" reads as ten thousand dollars to an agent that takes it
    literally, and the whole point of that field is that the agent should.
    """
    return None if minor is None else str(Money(minor, currency))


def _decision(payload: dict[str, Any]) -> dict[str, Any]:
    """A decision cut down to what an agent should act on."""
    currency = payload.get("currency") or "USD"
    trace = payload.get("trace") or []
    refused_by = [
        {"rule": row.get("code"), "why": row.get("detail")}
        for row in trace
        if row.get("outcome") == "fail"
    ]
    return {
        "verdict": payload.get("verdict"),
        "amount": _major(payload.get("amount"), currency),
        "reason": payload.get("reason"),
        "refused_by": refused_by,
        "largest_that_would_clear": _major(payload.get("max_allowable"), currency),
        "remaining_after": _major(payload.get("remaining_after"), currency),
        "attempt_id": payload.get("attempt_id"),
        "next": (
            "Held. Nothing has moved yet; the person releases holds from the Leash screen."
            if payload.get("verdict") == "allow"
            else "Refused. Nothing was held. Choose something inside the limits above."
        ),
    }


def build(
    *,
    store: Callable[[], Store],
    catalog: Callable[[], Catalog],
    settings: Callable[[], Settings],
    mandate_id: str = DEMO_MANDATE_ID,
) -> MCPServer:
    """An MCP server over the same store the HTTP API and the screen use.

    Every refusal a tool can see coming is a ToolError, not a ValueError.
    The SDK masks any other exception as "Error executing tool ...", so an
    agent that passed a payee it made up was never told to use the one from
    a search result, which is the one thing it needed to hear.

    Takes getters rather than instances because the store is replaced
    whenever the demo is reset, and a tool should always see the live one.
    """
    server = MCPServer(
        name="leash",
        title="Leash",
        description="Scoped, revocable, auditable spending authority for AI agents",
        instructions=INSTRUCTIONS,
        website_url="https://leash-web.onrender.com",
    )

    def ledger() -> Ledger:
        return store().ledger(mandate_id)

    @server.tool(
        name="read_mandate",
        title="Read the mandate",
        description=(
            "What you are allowed to spend: the total, the caps per purchase and per "
            "merchant, allowed categories, the pace limit, when it expires, and how much "
            "is left. Read this before asking to spend."
        ),
        annotations=_READ,
    )
    def read_mandate() -> dict[str, Any]:
        book = ledger()
        summary = dict(book.summary())
        return {
            "status": summary["status"],
            "available": _money(book.available),
            "held": _money(book.held),
            "committed": _money(book.committed),
            "terms": _terms(book.mandate),
            "you_can": "search and ask to spend; a person releases what you are allowed",
        }

    @server.tool(
        name="search_products",
        title="Search products",
        description=(
            "Search a live product catalogue. Each result gives the payee and category to "
            "use with request_purchase. Searching makes those merchants payable."
        ),
        annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True),
    )
    async def search_products(
        query: Annotated[str, Field(description="What to look for, in plain words, e.g. 'office chair'.")],
        max_price: Annotated[
            float | None,
            Field(description="Only show offers at or under this price, in the mandate's currency."),
        ] = None,
    ) -> dict[str, Any]:
        if not query.strip():
            raise ToolError("a search needs a query")
        book = ledger()
        ceiling = None
        if max_price is not None:
            ceiling = Money.from_major(Decimal(str(max_price)), book.mandate.currency)
        try:
            items = await catalog().search(query, under=ceiling, limit=8)
        except CatalogError as exc:
            raise ToolError(f"the catalogue could not be reached: {exc}") from exc
        register_merchants(store(), items, settings())

        results = []
        for item in items:
            best = item.best
            if best is None:
                continue
            results.append(
                {
                    "title": item.title,
                    "brand": item.brand or None,
                    "category": item.category,
                    "payee": best.payee,
                    "price": str(best.price),
                    "amount": str(best.price.major),
                    "merchant": best.domain,
                    "url": best.url or None,
                    "other_offers": len(item.offers) - 1,
                }
            )
        return {"query": query, "results": results}

    @server.tool(
        name="request_purchase",
        title="Request a purchase",
        description=(
            "Ask to spend. Returns 'allow', in which case the money is held against the "
            "budget until a person releases it, or 'block', with every rule that refused "
            "it and the largest amount that would have cleared. Use the payee and category "
            "from search_products. Pass the same idempotency_key when retrying one request, "
            "so a retry can never hold the money twice."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False
        ),
    )
    def request_purchase(
        payee: Annotated[str, Field(description="The payee id from a search result, e.g. 'overstock_com'.")],
        amount: Annotated[str, Field(description="The price, e.g. '97.99'.")],
        category: Annotated[str, Field(description="The category from the search result, e.g. 'furniture'.")],
        description: Annotated[str, Field(description="What it is, for the audit log.")] = "",
        idempotency_key: Annotated[
            str | None, Field(description="Reuse this to retry one request without holding twice.")
        ] = None,
    ) -> dict[str, Any]:
        book = ledger()
        try:
            value = Decimal(str(amount).strip().lstrip("$"))
        except InvalidOperation as exc:
            raise ToolError(f"not an amount: {amount!r}") from exc
        if value <= 0:
            raise ToolError("an amount has to be more than zero")
        if not store().knows_payee(payee):
            raise ToolError(
                f"unknown payee {payee!r}; use the payee from a search_products result"
            )
        attempt = Attempt(
            id=f"att_{uuid.uuid4().hex[:10]}",
            mandate_id=book.mandate.id,
            payee=payee,
            category=category,
            amount=Money.from_major(value, book.mandate.currency),
            requested_at=datetime.now(timezone.utc),
            description=description or "requested by an outside agent over MCP",
            idempotency_key=idempotency_key,
        )
        return _decision(book.authorize(attempt).to_dict())

    @server.tool(
        name="recent_decisions",
        title="Recent decisions",
        description="The most recent requests against this mandate and what was decided, newest first.",
        annotations=_READ,
    )
    def recent_decisions(
        limit: Annotated[int, Field(ge=1, le=50, description="How many to return.")] = 10,
    ) -> dict[str, Any]:
        rows = ledger().rows()[-limit:][::-1]
        return {
            "decisions": [
                {
                    "verdict": r.get("verdict"),
                    "payee": r.get("payee"),
                    "amount": _major(r.get("amount"), r.get("currency") or "USD"),
                    "category": r.get("category"),
                    "reason": r.get("reason"),
                }
                for r in rows
            ]
        }

    return server


class Endpoint:
    """The streamable HTTP endpoint, rebuilt for every app lifespan.

    Three things about the SDK that are handled here rather than discovered
    in production.

    A mounted Starlette app's own lifespan never runs, and that lifespan is
    what starts the session manager. So it is started from FastAPI's.

    A session manager can only be started once, and the test suite starts
    the app afresh for every test. So each lifespan builds a new one.

    DNS-rebinding protection switches itself on whenever the host is
    localhost, and then accepts only a localhost Host header, which would
    refuse every request that reaches Render. It exists to stop a hostile web
    page reaching a server on your own machine. This one is public and
    unauthenticated on purpose, like the rest of the demo API, so it is off.
    """

    def __init__(self, server: MCPServer) -> None:
        self._server = server
        self._app: ASGIApp | None = None

    @asynccontextmanager
    async def running(self) -> AsyncIterator[None]:
        app = self._server.streamable_http_app(
            streamable_http_path="/mcp",
            # Every request stands alone. No session to lose when a free
            # instance sleeps and wakes, and nothing sticky to route.
            stateless_http=True,
            json_response=True,
            transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        )
        self._app = app
        try:
            async with self._server.session_manager.run():
                yield
        finally:
            self._app = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self._app is None:
            await JSONResponse(
                {"detail": "the agent endpoint is not running"}, status_code=503
            )(scope, receive, send)
            return
        await self._app(scope, receive, send)
