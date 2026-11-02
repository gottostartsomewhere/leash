"""Request and response shapes for the HTTP surface.

Amounts cross the wire as decimal strings in major units, because that is what
a person reads and what PayPal expects. They become integer minor units the
moment they are inside.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .models import Mandate
from .money import Money


class MoneyOut(BaseModel):
    model_config = ConfigDict(frozen=True)

    minor: int
    currency: str
    display: str

    @classmethod
    def of(cls, amount: Money) -> "MoneyOut":
        return cls(minor=amount.minor, currency=amount.currency, display=str(amount))


class VelocityIn(BaseModel):
    window_seconds: int = Field(gt=0)
    max_count: int | None = Field(default=None, ge=1)
    max_amount: Decimal | None = Field(default=None, gt=0)


class MandateIn(BaseModel):
    """What the person is willing to let an agent do."""

    agent_id: str
    total_limit: Decimal = Field(gt=0)
    currency: str = "USD"
    duration_hours: float = Field(default=720.0, gt=0)

    id: str | None = None
    per_item_limit: Decimal | None = Field(default=None, gt=0)
    per_payee_limit: Decimal | None = Field(default=None, gt=0)
    allowed_categories: list[str] | None = None
    allowed_payees: list[str] | None = None
    velocity: VelocityIn | None = None
    concentration_max_share: float | None = Field(default=None, gt=0, le=1)
    concentration_floor: Decimal | None = Field(default=None, gt=0)
    structuring_window_seconds: int = Field(default=900, ge=0)


class AttemptIn(BaseModel):
    """One proposed spend, submitted by the agent."""

    payee: str
    category: str
    amount: Decimal = Field(gt=0)
    currency: str = "USD"
    description: str = ""
    idempotency_key: str | None = None
    id: str | None = None


class PayoutRequest(BaseModel):
    """The approval step: which held charges a human is releasing."""

    charge_ids: list[str] = Field(min_length=1)


class ShopRequest(BaseModel):
    """What the agent has been sent out to buy, in words."""

    needs: list[str] = Field(min_length=1, max_length=10)
    reshop: bool = True


class PayeeOut(BaseModel):
    id: str
    name: str
    email: str
    counterparty: str


class ChargeOut(BaseModel):
    id: str
    payee: str
    category: str
    amount: MoneyOut
    state: str
    created_at: str
    description: str = ""


# -- what comes back ------------------------------------------------------
#
# These exist so the OpenAPI definition describes the answers, not just the
# questions. Without them, a generated SDK hands a caller an untyped bag for
# `POST /attempts`, which is the one call that matters: the refusal contract
# is the product here, so it belongs in the specification. Declaring them as
# `response_model` also means the specification cannot quietly drift from
# what the handlers actually return.


class HealthOut(BaseModel):
    status: str
    gateway: str
    catalog: str
    paypal_configured: bool
    channel3_configured: bool
    groq_configured: bool
    #: Names of the LEASH_ variables this process can see. Never values.
    configured: list[str] = Field(default_factory=list)


class CheckOut(BaseModel):
    """One rule, what it decided, and the numbers it decided on."""

    code: str = Field(description="Which rule this is, e.g. `structuring`.")
    outcome: str = Field(description="`pass`, `fail`, or `skip` when not configured.")
    severity: str = Field(description="`medium`, `high` or `critical`.")
    detail: str
    evidence: dict[str, Any] = Field(
        default_factory=dict,
        description="The numbers behind the decision. Shape varies by rule.",
    )


class DecisionOut(BaseModel):
    """The answer to "may I spend this", with its full working shown."""

    attempt_id: str
    mandate_id: str
    verdict: str = Field(description="`allow` or `block`.")
    evaluated_at: str
    reason: str = Field(description="One sentence, for a person.")
    amount: int = Field(description="Minor units, e.g. 1050 is 10.50.")
    currency: str
    payee: str
    category: str
    available: int
    remaining_after: int
    max_allowable: int = Field(
        description=(
            "The largest amount that would have cleared every rule right now. "
            "Zero when no amount would. This is what turns a refusal into a "
            "boundary an agent can act on rather than a wall."
        )
    )
    failed_codes: list[str]
    trace: list[CheckOut] = Field(
        description="Every rule that ran, including the ones that passed."
    )


class VelocityOut(BaseModel):
    window_seconds: int
    max_count: int | None = None
    max_amount: int | None = None


class TermsOut(BaseModel):
    """What the authority actually permits."""

    per_item_limit: int | None = None
    per_payee_limit: int | None = None
    allowed_categories: list[str] | None = None
    allowed_payees: list[str] | None = None
    velocity: VelocityOut | None = None
    concentration_max_share: float | None = None
    concentration_floor: int | None = None
    structuring_window_seconds: int
    starts_at: str
    ends_at: str
    revoked_at: str | None = None


class BalancesOut(BaseModel):
    """How much of the authority is left."""

    mandate_id: str
    agent_id: str
    status: str
    currency: str
    total_limit: int
    committed: int
    held: int = Field(description="Authorised but not yet captured.")
    available: int
    attempts: int
    blocked: int


class MandateOut(BalancesOut):
    terms: TermsOut


class AttemptOut(DecisionOut):
    summary: BalancesOut


class RevokeOut(BaseModel):
    revoked: bool
    released_charge_ids: list[str]
    summary: BalancesOut


class ReleaseOut(BaseModel):
    charge: ChargeOut
    summary: BalancesOut


class PayoutItemOut(BaseModel):
    charge_id: str
    status: str
    payout_item_id: str | None = None


class PayoutBatchOut(BaseModel):
    batch_id: str
    status: str
    gateway: str
    settled: bool
    items: list[PayoutItemOut] = Field(default_factory=list)


class PayoutOut(BaseModel):
    batch: PayoutBatchOut
    settled_charge_ids: list[str]
    failed_charge_ids: list[str]
    summary: BalancesOut


class CorrectionOut(BaseModel):
    charge_id: str
    was: str
    now: str
    processor_status: str
    note: str = ""


class ReconcileOut(BaseModel):
    """What the processor said, and what the ledger had to change."""

    batch_id: str
    status: str
    gateway: str
    checked: int
    agreed: int
    clean: bool
    corrected: list[CorrectionOut] = Field(
        description="Fixed automatically. Money that came back frees budget."
    )
    conflicts: list[CorrectionOut] = Field(
        description=(
            "Reported, not fixed. The processor says it paid but the ledger "
            "gave the budget back, and re-committing it could push the "
            "mandate past its own limit."
        )
    )
    unknown: list[str]


class ReconcileAllOut(BaseModel):
    batches: list[ReconcileOut]
    clean: bool
    corrected: int
    conflicts: int


class OfferOut(BaseModel):
    """One merchant's price for one product."""

    domain: str
    payee: str
    counterparty: str = Field(
        description="Merchant hostnames group onto one counterparty, so the "
        "per-counterparty cap measures the merchant and not the URL."
    )
    amount: int
    currency: str
    display: str
    availability: str
    in_stock: bool
    url: str = ""
    condition: str | None = None


class ItemOut(BaseModel):
    id: str
    title: str
    brand: str = ""
    category: str = ""
    image_url: str = ""
    offers: list[OfferOut]
    best: OfferOut | None = Field(
        default=None, description="Cheapest offer that is actually in stock."
    )
    counterparties: list[str]


class CatalogOut(BaseModel):
    catalog: str
    query: str
    items: list[ItemOut]
    new_payees: list[str] = Field(
        description="Merchants that became payable as a result of this search."
    )


class ShopStepOut(BaseModel):
    query: str
    note: str = ""
    action: str = Field(
        description=(
            "`bought`, `reshopped` when a refusal sent it back to the shop "
            "under a price ceiling, `refused`, `nothing_found`, `unreachable`."
        )
    )
    summary: str
    detail: str = ""
    item: ItemOut | None = None
    offer: OfferOut | None = None
    first_choice: ItemOut | None = Field(
        default=None, description="What it wanted before being refused."
    )
    ceiling: int | None = Field(
        default=None, description="The counter-offer it shopped against."
    )
    decision: DecisionOut | None = None


class ShopOut(BaseModel):
    steps: list[ShopStepOut]
    summary: BalancesOut


class SeededPayeeOut(BaseModel):
    id: str
    name: str
    email: str
    counterparty: str


class ResetOut(BaseModel):
    reset: bool
    mandate_id: str
    payees: list[SeededPayeeOut]


def terms(mandate: Mandate) -> dict[str, Any]:
    """Everything the mandate permits, in one readable object.

    The balance summary says how much is left. This says what the authority
    actually is, which is the part a person has to be able to read back before
    they hand it to an agent.
    """
    minor = lambda amount: None if amount is None else amount.minor  # noqa: E731
    velocity = mandate.velocity
    return {
        "per_item_limit": minor(mandate.per_item_limit),
        "per_payee_limit": minor(mandate.per_payee_limit),
        "allowed_categories": (
            sorted(mandate.allowed_categories)
            if mandate.allowed_categories is not None
            else None
        ),
        "allowed_payees": (
            sorted(mandate.allowed_payees)
            if mandate.allowed_payees is not None
            else None
        ),
        "velocity": (
            None
            if velocity is None
            else {
                "window_seconds": velocity.window_seconds,
                "max_count": velocity.max_count,
                "max_amount": minor(velocity.max_amount),
            }
        ),
        "concentration_max_share": mandate.concentration_max_share,
        "concentration_floor": minor(mandate.concentration_floor),
        "structuring_window_seconds": mandate.structuring_window_seconds,
        "starts_at": mandate.starts_at.isoformat(),
        "ends_at": mandate.ends_at.isoformat(),
        "revoked_at": (
            None if mandate.revoked_at is None else mandate.revoked_at.isoformat()
        ),
    }
