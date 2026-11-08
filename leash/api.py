"""HTTP surface.

The flow the demo follows: an agent posts an attempt, the engine decides, an
allow places a hold, a human approves a set of holds, and only then does one
PayPal batch move the money. The payout result comes back per item and lands
on the charge, so the grid tells the truth about what actually settled.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated, Any, AsyncIterator, Callable, Literal, TypeVar

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from . import drafting, mcp_server
from .adversary import LLMAdversary, StrategyAdversary
from .agent import Need, ShoppingAgent
from .catalog import Catalog, CatalogError, build_catalog
from .config import Settings, settings as default_settings
from .ledger import IllegalTransition, Ledger, UnknownCharge
from .llm import build_brain
from .models import Attempt, Charge, Mandate, Velocity
from .money import Money
from .payouts import (
    PayoutError,
    PayoutGateway,
    PayoutItem,
    build_gateway,
    holds_money,
)
from .reconcile import reconcile_all, reconcile_batch
from .redteam import ALL_OBJECTIVES, Suite, run_campaign, world_from
from .schemas import (
    AttackOut,
    AttemptIn,
    DraftIn,
    DraftOut,
    AttemptOut,
    CatalogOut,
    ChargeOut,
    HealthOut,
    MandateIn,
    DecisionOut,
    MandateOut,
    MoneyOut,
    PayeeOut,
    PayoutOut,
    PayoutBatchOut,
    PayoutRequest,
    ReconcileAllOut,
    ReconcileOut,
    ReleaseOut,
    ResetOut,
    RevokeOut,
    ShopOut,
    ShopRequest,
    terms,
)
from .store import (
    DEMO_MANDATE_ID,
    NotFound,
    Store,
    build_demo_store,
    new_batch_id,
    register_merchants,
    seed_demo,
    seed_summary,
)

#: Groups in the generated documentation and SDKs. Ordered the way someone
#: integrating actually meets them, not alphabetically.
TAGS = [
    {
        "name": "mandates",
        "description": "Open an authority, read its terms, pull it.",
    },
    {
        "name": "spending",
        "description": (
            "The one call that matters. An agent asks, and gets back a "
            "verdict, every rule that ran, and what would have cleared."
        ),
    },
    {
        "name": "catalogue",
        "description": "What the agent can see in the shop, and sending it shopping.",
    },
    {
        "name": "money",
        "description": (
            "Approval and settlement over PayPal Payouts, and reconciling the "
            "ledger against what the processor actually did."
        ),
    },
    {"name": "demo", "description": "Rebuild the seeded scenario."},
]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Start the agent endpoint's session manager. See `mcp_server.Endpoint`."""
    async with agent_endpoint.running():
        yield


app = FastAPI(
    lifespan=lifespan,
    title="Leash",
    version="0.1.0",
    summary="Scoped, revocable, auditable spending authority for AI agents",
    description=(
        "Leash gives an AI agent a budget with terms attached, and judges "
        "every spend against them.\n\n"
        "Three things are worth knowing before integrating.\n\n"
        "**Amounts are integer minor units** with the currency beside them. "
        "`1050` in `USD` is $10.50. No amount is ever a decimal number on "
        "this wire, so nothing can be lost to floating point.\n\n"
        "**A refusal is a boundary, not a wall.** Every blocked attempt "
        "carries `max_allowable`: the largest amount that would have cleared "
        "right now. An agent told 150 is too much is also told that 100 would "
        "go through, so it can act rather than give up.\n\n"
        "**Every rule runs on every attempt.** `trace` carries all of them, "
        "passed and failed, with the numbers each one decided on. A refusal "
        "names every reason rather than the first one found, so an agent "
        "never fixes one problem only to meet the next.\n\n"
        "**Any agent can be put on a Leash.** The same mandate is served over "
        "the Model Context Protocol at `/mcp`, so Claude, ChatGPT or any MCP "
        "client can read it, shop and ask to spend, through the same checks "
        "and into the same audit log. It has no tool that moves money."
    ),
    license_info={
        "name": "MIT",
        "url": "https://github.com/gottostartsomewhere/leash/blob/main/LICENSE",
    },
    openapi_tags=TAGS,
    servers=[
        {"url": "https://leash-api-sm0h.onrender.com", "description": "Live demo"},
        {"url": "http://127.0.0.1:8000", "description": "Local"},
    ],
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_store: Store | None = None
_gateway: PayoutGateway | None = None
_catalog: Catalog | None = None


def get_settings() -> Settings:
    return default_settings()


def get_store() -> Store:
    global _store
    if _store is None:
        _store = build_demo_store()
    return _store


def get_gateway() -> PayoutGateway:
    global _gateway
    if _gateway is None:
        _gateway = build_gateway()
    return _gateway


def get_catalog() -> Catalog:
    global _catalog
    if _catalog is None:
        _catalog = build_catalog()
    return _catalog


StoreDep = Annotated[Store, Depends(get_store)]
GatewayDep = Annotated[PayoutGateway, Depends(get_gateway)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
CatalogDep = Annotated[Catalog, Depends(get_catalog)]

_T = TypeVar("_T")


def _live(getter: Callable[[], _T]) -> Callable[[], _T]:
    """A getter that honours dependency overrides.

    The HTTP routes get the store through `Depends`, which the test suite
    overrides, while the MCP tools call a getter directly, which it does not.
    Without this the two would quietly diverge in tests: an outside agent's
    purchase would land in one store while the assertions read another.
    """
    return lambda: app.dependency_overrides.get(getter, getter)()


# The same mandate, served to agents that are not ours. See mcp_server.
agent_server = mcp_server.build(
    store=_live(get_store), catalog=_live(get_catalog), settings=_live(get_settings)
)
agent_endpoint = mcp_server.Endpoint(agent_server)
app.add_route(
    "/mcp", agent_endpoint, methods=["GET", "POST", "DELETE"], include_in_schema=False
)


def _ledger(store: Store, mandate_id: str) -> Ledger:
    try:
        return store.ledger(mandate_id)
    except NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _charge_row(charge: Charge) -> ChargeOut:
    return ChargeOut(
        id=charge.id,
        payee=charge.payee,
        category=charge.category,
        amount=MoneyOut.of(charge.amount),
        state=charge.state.value,
        created_at=charge.created_at.isoformat(),
        description=charge.description,
    )


# -- health and demo control ---------------------------------------------


@app.get("/health", response_model=HealthOut, tags=["demo"])
def health(
    settings: SettingsDep, gateway: GatewayDep, catalog: CatalogDep
) -> dict[str, Any]:
    """What this process is, and what it can see.

    `configured` lists the names of the LEASH_ variables present, never their
    values. On a deployed service you cannot look at the environment, and the
    difference between "the key is missing" and "the key is there under a
    slightly different name" is otherwise invisible. Those names are already
    public in .env.example, so listing them gives nothing away.
    """
    return {
        "status": "ok",
        "gateway": gateway.name,
        "catalog": catalog.name,
        "paypal_configured": settings.paypal_configured,
        "channel3_configured": settings.channel3_configured,
        "groq_configured": settings.groq_configured,
        "configured": sorted(
            name for name, value in os.environ.items()
            if name.startswith("LEASH_") and value.strip()
        ),
    }


@app.post("/demo/reset", response_model=ResetOut, tags=["demo"])
def reset_demo(store: StoreDep, settings: SettingsDep) -> dict[str, Any]:
    """Rebuild the seeded scenario. Lets a take be re-recorded in a second."""
    seed_demo(store, settings)
    return {"reset": True, **seed_summary(store)}


@app.get("/payees", response_model=list[PayeeOut], tags=["demo"])
def list_payees(store: StoreDep) -> list[PayeeOut]:
    return [
        PayeeOut(id=p.id, name=p.name, email=p.email, counterparty=p.counterparty)
        for p in store.payees()
    ]


# -- the catalogue --------------------------------------------------------


@app.get("/catalog/search", response_model=CatalogOut, tags=["catalogue"])
async def search_catalog(
    q: str,
    store: StoreDep,
    catalog: CatalogDep,
    settings: SettingsDep,
    under: Decimal | None = None,
    currency: str = "USD",
    limit: int = 8,
) -> dict[str, Any]:
    """What the agent can see in the shop.

    Every merchant that comes back is registered as a payee, with its
    hostnames grouped onto one counterparty, so a spend against it can be
    judged the moment the agent asks.
    """
    if not q.strip():
        raise HTTPException(status_code=422, detail="a search needs a query")
    ceiling = None if under is None else Money.from_major(under, currency)

    try:
        items = await catalog.search(q, under=ceiling, limit=max(1, min(limit, 24)))
    except CatalogError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    registered = register_merchants(store, items, settings)
    return {
        "catalog": catalog.name,
        "query": q,
        "items": [item.to_dict() for item in items],
        "new_payees": [p.id for p in registered],
    }


@app.post("/mandates/{mandate_id}/shop", response_model=ShopOut, tags=["catalogue"])
async def shop(
    mandate_id: str,
    body: ShopRequest,
    store: StoreDep,
    catalog: CatalogDep,
    settings: SettingsDep,
) -> dict[str, Any]:
    """Send the agent shopping against this mandate.

    The interesting path is a refusal: told what would clear, the agent goes
    back to the catalogue with that as a price ceiling and buys something
    that fits, rather than arguing about the thing it cannot have.
    """
    ledger = _ledger(store, mandate_id)
    agent = ShoppingAgent(
        ledger,
        catalog,
        reshop=body.reshop,
        # A model picks the product when one is configured, and the
        # catalogue's own ranking picks when it is not. Either way the same
        # eleven checks decide whether the pick is allowed, which is the
        # point: the agent proposes, the mandate disposes.
        brain=build_brain(settings),
        # Merchants become known the moment they are seen, before anything is
        # asked for, so the first spend is judged against a grouped
        # counterparty rather than an unknown name.
        on_found=lambda items: register_merchants(store, items, settings),
    )

    steps = await agent.run(Need(query=query) for query in body.needs)

    return {
        "steps": [step.to_dict() for step in steps],
        "summary": dict(ledger.summary()),
    }


# -- mandates -------------------------------------------------------------


def _mandate_view(ledger: Ledger) -> dict[str, Any]:
    """Balances and terms together: how much is left, and what it may go on."""
    return {**dict(ledger.summary()), "terms": terms(ledger.mandate)}


@app.get("/mandates", response_model=list[MandateOut], tags=["mandates"])
def list_mandates(store: StoreDep) -> list[dict[str, Any]]:
    return [_mandate_view(ledger) for ledger in store.ledgers()]


def mandate_from(body: MandateIn, *, mandate_id: str | None = None) -> Mandate:
    """A mandate from its terms, the one way every mandate is built.

    Hand-written, drafted by a model from plain English, or signed into the
    demo, they all come through here, so a model's draft is held to exactly
    the rules a person's is. Raises ValueError for terms that do not make a
    mandate.
    """
    now = datetime.now(timezone.utc)
    currency = body.currency

    def money(value: Any) -> Money | None:
        return None if value is None else Money.from_major(value, currency)

    velocity = None
    if body.velocity is not None:
        velocity = Velocity(
            window_seconds=body.velocity.window_seconds,
            max_count=body.velocity.max_count,
            max_amount=money(body.velocity.max_amount),
        )

    return Mandate(
        id=mandate_id or body.id or f"mnd_{uuid.uuid4().hex[:10]}",
        agent_id=body.agent_id,
        currency=currency,
        total_limit=Money.from_major(body.total_limit, currency),
        starts_at=now,
        ends_at=now + timedelta(hours=body.duration_hours),
        per_item_limit=money(body.per_item_limit),
        per_payee_limit=money(body.per_payee_limit),
        allowed_categories=(
            frozenset(body.allowed_categories) if body.allowed_categories else None
        ),
        allowed_payees=(frozenset(body.allowed_payees) if body.allowed_payees else None),
        velocity=velocity,
        concentration_max_share=body.concentration_max_share,
        concentration_floor=money(body.concentration_floor),
        structuring_window_seconds=body.structuring_window_seconds,
    )


@app.post("/mandates", status_code=201, response_model=MandateOut, tags=["mandates"])
def create_mandate(body: MandateIn, store: StoreDep) -> dict[str, Any]:
    try:
        mandate = mandate_from(body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _mandate_view(store.open(mandate))


@app.get("/mandates/{mandate_id}", response_model=MandateOut, tags=["mandates"])
def get_mandate(mandate_id: str, store: StoreDep) -> dict[str, Any]:
    return _mandate_view(_ledger(store, mandate_id))


@app.post("/mandates/{mandate_id}/revoke", response_model=RevokeOut, tags=["mandates"])
def revoke_mandate(mandate_id: str, store: StoreDep) -> dict[str, Any]:
    """Pull the mandate. Pending holds drop; anything settled stays settled."""
    ledger = _ledger(store, mandate_id)
    dropped = ledger.revoke()
    return {
        "revoked": True,
        "released_charge_ids": [c.id for c in dropped],
        "summary": dict(ledger.summary()),
    }


#: One model attack at a time. Each one is a few dozen calls to a free model
#: tier, and a handful of judges pressing the button together would spend
#: the rate limit on each other instead of on the mandate.
_model_attack = asyncio.Lock()

_CAMPAIGN_FIELDS = (
    "objective", "description", "attempts", "allowed", "blocked", "held", "breach", "by_code",
)
_MOVE_FIELDS = (
    "sequence", "strategy", "payee", "category", "amount", "currency",
    "rationale", "verdict", "codes", "headline",
)


@app.post("/mandates/{mandate_id}/attack", response_model=AttackOut, tags=["mandates"])
async def attack_mandate(
    mandate_id: str,
    store: StoreDep,
    settings: SettingsDep,
    by: Literal["strategy", "model"] = "strategy",
) -> dict[str, Any]:
    """Point an attacker at this mandate, and report what got through.

    Five objectives: beat the per-purchase cap, beat the per-merchant cap,
    spend past the total, buy outside the categories, spend after
    revocation. `by=strategy` is the exhaustive deterministic search, around
    three hundred attempts in tens of milliseconds. `by=model` hands the same
    objectives to a language model, which is slower, tries far fewer things,
    and is the attacker that has found real bugs.

    It runs on a sandbox: a fresh ledger built from this mandate's terms and
    seeded with the charges it already holds. So it attacks the mandate as it
    stands, including whatever is already spent, and leaves not one attempt
    behind in the real one.
    """
    ledger = _ledger(store, mandate_id)
    mandate = ledger.mandate
    world = world_from(store, mandate)
    seed = tuple(c for c in ledger.charges() if c.commits)

    if by == "model":
        brain = build_brain(settings)
        if brain is None:
            raise HTTPException(status_code=503, detail="no model is configured on this server")
        if _model_attack.locked():
            raise HTTPException(
                status_code=429, detail="a model attack is already running; try again in a moment"
            )
        adversary: Any = LLMAdversary(brain)
        max_attempts = 8
    else:
        adversary = StrategyAdversary()
        max_attempts = 120

    async def every_objective() -> Suite:
        start = datetime.now(timezone.utc)
        return Suite(
            tuple(
                [
                    await run_campaign(
                        mandate=mandate,
                        world=world,
                        objective=objective(),
                        adversary=adversary,
                        directory=store.directory,
                        max_attempts=max_attempts,
                        start=start,
                        seed_charges=seed,
                    )
                    for objective in ALL_OBJECTIVES
                ]
            )
        )

    began = time.perf_counter()
    if by == "model":
        async with _model_attack:
            suite = await every_objective()
    else:
        suite = await every_objective()
    elapsed = (time.perf_counter() - began) * 1000

    body = suite.to_dict()
    return {
        "adversary": adversary.name,
        "held": suite.held,
        "attempts": suite.attempts,
        "blocked": suite.blocked,
        "allowed": suite.attempts - suite.blocked,
        "breaches": body["breaches"],
        "elapsed_ms": round(elapsed),
        "sandboxed": True,
        "campaigns": [
            {
                **{k: c[k] for k in _CAMPAIGN_FIELDS},
                "log": [{k: m[k] for k in _MOVE_FIELDS} for m in c["log"]],
            }
            for c in body["campaigns"]
        ],
    }


@app.post("/mandates/draft", response_model=DraftOut, tags=["mandates"])
async def draft_mandate(body: DraftIn, store: StoreDep, settings: SettingsDep) -> dict[str, Any]:
    """Write a mandate in plain English, and see it checked and attacked first.

    A model turns the words into terms and lists what it had to assume and
    what it could not place. The engine then does what it does for any
    mandate: builds it with the same validation a hand-written one gets,
    reads it for what it leaves open, and attacks it. Nothing is signed.
    `mandate` in the reply is the exact body to sign, and signing is a
    separate request the person makes after reading all of this. The model
    drafts; it never decides what is allowed.
    """
    brain = build_brain(settings)
    if brain is None:
        raise HTTPException(status_code=503, detail="no model is configured on this server")
    try:
        drafted = await drafting.draft(body.text, brain)
        mandate = mandate_from(drafted.body, mandate_id="mnd_draft")
    except drafting.ModelUnavailable as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    world = world_from(store, mandate)
    adversary = StrategyAdversary()
    began = time.perf_counter()
    start = datetime.now(timezone.utc)
    suite = Suite(
        tuple(
            [
                await run_campaign(
                    mandate=mandate,
                    world=world,
                    objective=objective(),
                    adversary=adversary,
                    directory=store.directory,
                    max_attempts=120,
                    start=start,
                )
                for objective in ALL_OBJECTIVES
            ]
        )
    )
    return {
        "text": body.text,
        "drafted_by": drafted.drafted_by,
        "mandate": drafted.body.model_dump(mode="json"),
        "assumptions": list(drafted.assumptions),
        "unclear": list(drafted.unclear),
        "exposure": [e.to_dict() for e in drafting.exposure(mandate)],
        "attack": {
            "adversary": adversary.name,
            "attempts": suite.attempts,
            "held": suite.held,
            "breaches": [r.breach for r in suite.reports if r.breach],
            "elapsed_ms": round((time.perf_counter() - began) * 1000),
        },
    }


@app.post("/demo/mandate", response_model=ResetOut, tags=["demo"])
def sign_demo_mandate(body: MandateIn, store: StoreDep, settings: SettingsDep) -> dict[str, Any]:
    """Sign a mandate into the demo, replacing the default one.

    The demo runs on one mandate, so signing a drafted one starts it over
    with those terms and an empty log. The reset button puts the default
    back.
    """
    try:
        mandate = mandate_from(body, mandate_id=DEMO_MANDATE_ID)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    seed_demo(store, settings, mandate=mandate)
    return {"reset": True, **seed_summary(store)}


@app.get("/mandates/{mandate_id}/charges", response_model=list[ChargeOut], tags=["money"])
def list_charges(mandate_id: str, store: StoreDep) -> list[ChargeOut]:
    return [_charge_row(c) for c in _ledger(store, mandate_id).charges()]


@app.get("/mandates/{mandate_id}/decisions", response_model=list[DecisionOut], tags=["spending"])
def list_decisions(mandate_id: str, store: StoreDep) -> list[dict[str, Any]]:
    """Every decision with its full trace. This is the audit grid."""
    return [dict(row) for row in _ledger(store, mandate_id).rows()]


# -- the core endpoint ----------------------------------------------------


@app.post("/mandates/{mandate_id}/attempts", response_model=AttemptOut, tags=["spending"])
def authorize(mandate_id: str, body: AttemptIn, store: StoreDep) -> dict[str, Any]:
    """The agent asks to spend. Everything else in this file is bookkeeping."""
    ledger = _ledger(store, mandate_id)
    try:
        attempt = Attempt(
            id=body.id or f"att_{uuid.uuid4().hex[:10]}",
            mandate_id=mandate_id,
            payee=body.payee,
            category=body.category,
            amount=Money.from_major(body.amount, body.currency),
            requested_at=datetime.now(timezone.utc),
            description=body.description,
            idempotency_key=body.idempotency_key,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    decision = ledger.authorize(attempt)
    payload = decision.to_dict()
    payload["summary"] = dict(ledger.summary())
    return payload


# -- approval and settlement ---------------------------------------------


@app.post("/mandates/{mandate_id}/payouts", response_model=PayoutOut, tags=["money"])
async def release_payouts(
    mandate_id: str,
    body: PayoutRequest,
    store: StoreDep,
    gateway: GatewayDep,
) -> dict[str, Any]:
    """Approve held charges and move the money in one batch.

    The batch goes out before anything is marked settled. If the processor
    refuses, the holds stay held and the whole thing can be retried; a partial
    result settles what cleared and fails what did not, so the grid matches
    the money rather than our intentions.
    """
    ledger = _ledger(store, mandate_id)

    # Claim first, then go to the processor. Checking the charges were
    # pending and then awaiting PayPal left a second request free to pass
    # the same check during that await, and the same charges went out
    # twice. A claim is atomic and is released however this ends.
    try:
        claimed = ledger.claim(body.charge_ids)
    except UnknownCharge as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except IllegalTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    settled: list[str] = []
    failed: list[str] = []
    try:
        items: list[PayoutItem] = []
        for charge in claimed:
            try:
                payee = store.payee(charge.payee)
            except NotFound as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            items.append(
                PayoutItem(
                    charge_id=charge.id,
                    receiver=payee.email,
                    amount=charge.amount,
                    note=charge.description or f"{charge.category} via {payee.name}",
                )
            )

        batch_id = new_batch_id()
        try:
            result = await gateway.send(items, batch_id=batch_id)
        except PayoutError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        store.record_batch(result)

        by_charge = {item.charge_id: item.status for item in result.items}
        for item in items:
            status = by_charge.get(item.charge_id, result.status)
            try:
                if holds_money(status):
                    ledger.settle(item.charge_id)
                    settled.append(item.charge_id)
                else:
                    ledger.fail(item.charge_id)
                    failed.append(item.charge_id)
            except IllegalTransition as exc:  # pragma: no cover - the claim holds it
                raise HTTPException(status_code=409, detail=str(exc)) from exc
    finally:
        ledger.unclaim(c.id for c in claimed)

    return {
        "batch": result.to_dict(),
        "settled_charge_ids": settled,
        "failed_charge_ids": failed,
        "summary": dict(ledger.summary()),
    }


@app.post("/charges/{charge_id}/release", response_model=ReleaseOut, tags=["money"])
def release_hold(charge_id: str, store: StoreDep) -> dict[str, Any]:
    """Decline a held charge and give the budget back."""
    try:
        ledger, _ = store.locate_charge(charge_id)
    except NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    try:
        charge = ledger.release(charge_id)
    except IllegalTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"charge": _charge_row(charge).model_dump(), "summary": dict(ledger.summary())}


@app.get("/payouts/{batch_id}", response_model=PayoutBatchOut, tags=["money"])
async def payout_status(
    batch_id: str, store: StoreDep, gateway: GatewayDep
) -> dict[str, Any]:
    """Live status from the processor, falling back to what we recorded."""
    try:
        return (await gateway.status(batch_id)).to_dict()
    except PayoutError:
        try:
            return store.batch(batch_id).to_dict()
        except NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/payouts/{batch_id}/reconcile", response_model=ReconcileOut, tags=["money"])
async def reconcile_one(
    batch_id: str, store: StoreDep, gateway: GatewayDep
) -> dict[str, Any]:
    """Re-read a batch and move the ledger to match what the processor says.

    A charge settles the moment the processor accepts the instruction, which
    is before it knows whether the item will land. This is the step that goes
    back and checks, so the grid ends up describing what happened rather than
    what we meant to happen.
    """
    try:
        report = await reconcile_batch(store, gateway, batch_id)
    except PayoutError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return report.to_dict()


@app.post("/payouts/reconcile", response_model=ReconcileAllOut, tags=["money"])
async def reconcile_everything(
    store: StoreDep, gateway: GatewayDep
) -> dict[str, Any]:
    """Every batch this process has sent, re-checked against the processor."""
    try:
        reports = await reconcile_all(store, gateway)
    except PayoutError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "batches": [report.to_dict() for report in reports],
        "clean": all(report.clean for report in reports),
        "corrected": sum(len(report.corrected) for report in reports),
        "conflicts": sum(len(report.conflicts) for report in reports),
    }
