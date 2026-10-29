"""Domain types for agent spending mandates.

A mandate is a scoped, revocable spending authority. An agent carries one, and
every attempt to spend is evaluated against it before any money moves.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from .money import Money


class MandateStatus(str, Enum):
    ACTIVE = "active"
    REVOKED = "revoked"


class ChargeState(str, Enum):
    PENDING = "pending"  # authorized, funds held, not captured yet
    SETTLED = "settled"  # captured
    RELEASED = "released"  # hold voided, budget returned
    FAILED = "failed"  # processor rejected it


#: States that still consume budget. A hold is as real as a capture until it
#: is released, which is the whole reason authorization and capture are
#: separate steps.
COMMITTING = frozenset({ChargeState.PENDING, ChargeState.SETTLED})


class Verdict(str, Enum):
    ALLOW = "allow"
    BLOCK = "block"


class Outcome(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"  # not configured on this mandate


class Severity(int, Enum):
    MEDIUM = 10
    HIGH = 20
    CRITICAL = 30


class CheckCode(str, Enum):
    MANDATE_INACTIVE = "mandate_inactive"
    CURRENCY_MISMATCH = "currency_mismatch"
    OUTSIDE_WINDOW = "outside_window"
    PAYEE_NOT_ALLOWED = "payee_not_allowed"
    CATEGORY_NOT_ALLOWED = "category_not_allowed"
    STRUCTURING = "structuring"
    PER_ITEM_LIMIT = "per_item_limit"
    PER_PAYEE_LIMIT = "per_payee_limit"
    INSUFFICIENT_BUDGET = "insufficient_budget"
    VELOCITY = "velocity"
    CONCENTRATION = "concentration"


#: Structuring outranks the cap it evades. A charge over the limit is a mistake;
#: two charges engineered to sit under it is intent, and the headline reason
#: shown to a human should say so.
SEVERITY: Mapping[CheckCode, Severity] = MappingProxyType(
    {
        CheckCode.MANDATE_INACTIVE: Severity.CRITICAL,
        CheckCode.CURRENCY_MISMATCH: Severity.CRITICAL,
        CheckCode.STRUCTURING: Severity.CRITICAL,
        CheckCode.OUTSIDE_WINDOW: Severity.HIGH,
        CheckCode.PAYEE_NOT_ALLOWED: Severity.HIGH,
        CheckCode.CATEGORY_NOT_ALLOWED: Severity.HIGH,
        CheckCode.CONCENTRATION: Severity.MEDIUM,
        CheckCode.VELOCITY: Severity.MEDIUM,
        CheckCode.PER_ITEM_LIMIT: Severity.MEDIUM,
        CheckCode.PER_PAYEE_LIMIT: Severity.MEDIUM,
        CheckCode.INSUFFICIENT_BUDGET: Severity.MEDIUM,
    }
)


def _require_aware(moment: datetime, label: str) -> None:
    if moment.tzinfo is None or moment.tzinfo.utcoffset(moment) is None:
        raise ValueError(f"{label} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class Velocity:
    """A ceiling on how fast, not just how much.

    An agent that spends its whole budget correctly but in nine seconds is
    usually a loop that got away from someone.
    """

    window_seconds: int
    max_count: int | None = None
    max_amount: Money | None = None

    def __post_init__(self) -> None:
        if self.window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        if self.max_count is None and self.max_amount is None:
            raise ValueError("velocity needs a count ceiling, an amount ceiling, or both")
        if self.max_count is not None and self.max_count < 1:
            raise ValueError("max_count must be at least 1")


class PayeeDirectory:
    """Resolves payee ids to the counterparty actually behind them.

    A merchant with three receiver addresses is still one merchant, and an
    agent splitting a charge across them is still structuring. Without this,
    every cluster check is one alias away from being useless.
    """

    def __init__(self, groups: Mapping[str, str] | None = None) -> None:
        self._groups = dict(groups or {})

    def register(self, payee: str, group: str) -> None:
        self._groups[payee] = group

    def group(self, payee: str) -> str:
        return self._groups.get(payee, payee)

    def aliases_of(self, group: str) -> frozenset[str]:
        members = {p for p, g in self._groups.items() if g == group}
        members.add(group)
        return frozenset(members)


@dataclass(frozen=True, slots=True)
class Mandate:
    """What an agent is allowed to spend, on what, with whom, and until when."""

    id: str
    agent_id: str
    currency: str
    total_limit: Money
    starts_at: datetime
    ends_at: datetime

    per_item_limit: Money | None = None
    per_payee_limit: Money | None = None
    allowed_categories: frozenset[str] | None = None  # None means any
    allowed_payees: frozenset[str] | None = None  # None means any
    velocity: Velocity | None = None
    concentration_max_share: float | None = None  # 0 < share <= 1

    #: Concentration is meaningless on a small book: the first payee is always
    #: 100% of it. The share rule only starts biting once this much has been
    #: committed.
    concentration_floor: Money | None = None

    #: How far back a cluster of charges to one counterparty is read as one
    #: purchase that was broken up. Fifteen minutes by default: long enough to
    #: catch a split, short enough not to merge two genuine purchases.
    structuring_window_seconds: int = 900

    status: MandateStatus = MandateStatus.ACTIVE
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_aware(self.starts_at, "starts_at")
        _require_aware(self.ends_at, "ends_at")
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        if self.structuring_window_seconds < 0:
            raise ValueError("structuring_window_seconds cannot be negative")

        currency = self.currency.upper()
        object.__setattr__(self, "currency", currency)
        for label in (
            "total_limit",
            "per_item_limit",
            "per_payee_limit",
            "concentration_floor",
        ):
            amount = getattr(self, label)
            if amount is not None and amount.currency != currency:
                raise ValueError(f"{label} is {amount.currency}, mandate is {currency}")
        if self.total_limit.minor < 0:
            raise ValueError("total_limit cannot be negative")

        velocity = self.velocity
        if velocity is not None and velocity.max_amount is not None:
            if velocity.max_amount.currency != currency:
                raise ValueError("velocity.max_amount currency does not match the mandate")

        share = self.concentration_max_share
        if share is not None and not (0 < share <= 1):
            raise ValueError("concentration_max_share must be in (0, 1]")
        if self.concentration_floor is not None and share is None:
            raise ValueError("concentration_floor needs a concentration_max_share")

        if self.revoked_at is not None:
            _require_aware(self.revoked_at, "revoked_at")

    def covers(self, moment: datetime) -> bool:
        return self.starts_at <= moment <= self.ends_at

    def revoked(self, at: datetime) -> "Mandate":
        """This mandate, dead from `at` onward. Revocation is never retroactive."""
        _require_aware(at, "at")
        return replace(self, status=MandateStatus.REVOKED, revoked_at=at)


@dataclass(frozen=True, slots=True)
class Attempt:
    """One proposed movement of money, before it is allowed to happen."""

    id: str
    mandate_id: str
    payee: str
    category: str
    amount: Money
    requested_at: datetime
    description: str = ""
    idempotency_key: str | None = None

    def __post_init__(self) -> None:
        _require_aware(self.requested_at, "requested_at")
        if self.amount.minor <= 0:
            raise ValueError("an attempt must be for a positive amount")


@dataclass(frozen=True, slots=True)
class Charge:
    """An authorized attempt, and the state of the money behind it."""

    id: str
    mandate_id: str
    payee: str
    category: str
    amount: Money
    created_at: datetime
    state: ChargeState = ChargeState.PENDING
    description: str = ""
    attempt_id: str | None = None

    def __post_init__(self) -> None:
        _require_aware(self.created_at, "created_at")

    @property
    def commits(self) -> bool:
        return self.state in COMMITTING

    def with_state(self, state: ChargeState, amount: Money | None = None) -> "Charge":
        return replace(self, state=state, amount=amount or self.amount)


@dataclass(frozen=True, slots=True)
class CheckResult:
    """One rule, what it decided, and the numbers it decided on.

    `evidence` is the point. A verdict a person cannot audit is a verdict they
    will eventually stop trusting.
    """

    code: CheckCode
    outcome: Outcome
    detail: str
    evidence: Mapping[str, object] = field(default_factory=dict)

    @property
    def severity(self) -> Severity:
        return SEVERITY[self.code]

    @property
    def failed(self) -> bool:
        return self.outcome is Outcome.FAIL

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code.value,
            "outcome": self.outcome.value,
            "severity": self.severity.name.lower(),
            "detail": self.detail,
            "evidence": dict(self.evidence),
        }
