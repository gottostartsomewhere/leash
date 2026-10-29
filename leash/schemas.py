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
