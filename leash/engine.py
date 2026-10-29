"""Mandate enforcement.

`evaluate` is pure: same mandate, same attempt, same history, same verdict.
Nothing here talks to a processor or a model, which is what makes the whole
thing testable against an adversary rather than demoable against a script.

Every check runs even after one has already failed, because a decision is
worth more when it says all three reasons rather than the first one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Callable, Iterable, Sequence

from .models import (
    SEVERITY,
    Attempt,
    Charge,
    CheckCode,
    CheckResult,
    Mandate,
    MandateStatus,
    Outcome,
    PayeeDirectory,
    Verdict,
)
from .money import Money


@dataclass(frozen=True, slots=True)
class Context:
    """Everything a check is allowed to look at."""

    mandate: Mandate
    attempt: Attempt
    history: tuple[Charge, ...]
    now: datetime
    directory: PayeeDirectory

    # -- derived views ---------------------------------------------------

    @property
    def currency(self) -> str:
        return self.mandate.currency

    @property
    def live(self) -> tuple[Charge, ...]:
        """Charges still consuming budget. Released and failed ones do not."""
        return tuple(c for c in self.history if c.commits)

    @property
    def committed(self) -> Money:
        return Money.sum((c.amount for c in self.live), self.currency)

    @property
    def available(self) -> Money:
        return (self.mandate.total_limit - self.committed).clamped()

    @property
    def target_group(self) -> str:
        return self.directory.group(self.attempt.payee)

    def spent_on(self, group: str) -> Money:
        return Money.sum(
            (c.amount for c in self.live if self.directory.group(c.payee) == group),
            self.currency,
        )

    def within(self, seconds: int) -> tuple[Charge, ...]:
        cutoff = self.now - timedelta(seconds=seconds)
        return tuple(c for c in self.live if c.created_at > cutoff)

    def cluster(self) -> tuple[Charge, ...]:
        """Recent charges to the same counterparty, under the per-item cap.

        These are the charges that, read together, may be one purchase that was
        taken apart.
        """
        limit = self.mandate.per_item_limit
        if limit is None:
            return ()
        window = self.mandate.structuring_window_seconds
        group = self.target_group
        return tuple(
            c
            for c in self.within(window)
            if self.directory.group(c.payee) == group and c.amount < limit
        )


Check = Callable[[Context], CheckResult]


def _ok(code: CheckCode, detail: str, **evidence: object) -> CheckResult:
    return CheckResult(code, Outcome.PASS, detail, evidence)


def _skip(code: CheckCode, detail: str = "not set on this mandate") -> CheckResult:
    return CheckResult(code, Outcome.SKIP, detail, {})


def _fail(code: CheckCode, detail: str, **evidence: object) -> CheckResult:
    return CheckResult(code, Outcome.FAIL, detail, evidence)


# -- checks ---------------------------------------------------------------


def check_mandate_active(ctx: Context) -> CheckResult:
    m = ctx.mandate
    if m.status is MandateStatus.REVOKED:
        return _fail(
            CheckCode.MANDATE_INACTIVE,
            "mandate was revoked",
            revoked_at=m.revoked_at.isoformat() if m.revoked_at else None,
        )
    return _ok(CheckCode.MANDATE_INACTIVE, "mandate is active")


def check_currency(ctx: Context) -> CheckResult:
    got = ctx.attempt.amount.currency
    if got != ctx.currency:
        return _fail(
            CheckCode.CURRENCY_MISMATCH,
            f"attempt is in {got}, mandate is in {ctx.currency}",
            attempt_currency=got,
            mandate_currency=ctx.currency,
        )
    return _ok(CheckCode.CURRENCY_MISMATCH, f"both sides are {ctx.currency}")


def check_window(ctx: Context) -> CheckResult:
    m = ctx.mandate
    at = ctx.attempt.requested_at
    if not m.covers(at):
        side = "before it opens" if at < m.starts_at else "after it closes"
        return _fail(
            CheckCode.OUTSIDE_WINDOW,
            f"attempted {side}",
            requested_at=at.isoformat(),
            starts_at=m.starts_at.isoformat(),
            ends_at=m.ends_at.isoformat(),
        )
    return _ok(CheckCode.OUTSIDE_WINDOW, "inside the mandate window")


def check_payee_allowed(ctx: Context) -> CheckResult:
    allowed = ctx.mandate.allowed_payees
    if allowed is None:
        return _skip(CheckCode.PAYEE_NOT_ALLOWED, "any payee permitted")
    payee = ctx.attempt.payee
    if payee not in allowed and ctx.directory.group(payee) not in allowed:
        return _fail(
            CheckCode.PAYEE_NOT_ALLOWED,
            f"{payee} is not on the allowed list",
            payee=payee,
            group=ctx.directory.group(payee),
            allowed=sorted(allowed),
        )
    return _ok(CheckCode.PAYEE_NOT_ALLOWED, f"{payee} is allowed")


def check_category_allowed(ctx: Context) -> CheckResult:
    """Scope drift: the agent buying something outside what it was sent to buy."""
    allowed = ctx.mandate.allowed_categories
    if allowed is None:
        return _skip(CheckCode.CATEGORY_NOT_ALLOWED, "any category permitted")
    category = ctx.attempt.category
    if category not in allowed:
        return _fail(
            CheckCode.CATEGORY_NOT_ALLOWED,
            f"{category!r} is outside this mandate's scope",
            category=category,
            allowed=sorted(allowed),
        )
    return _ok(CheckCode.CATEGORY_NOT_ALLOWED, f"{category!r} is in scope")


def check_per_item(ctx: Context) -> CheckResult:
    limit = ctx.mandate.per_item_limit
    if limit is None:
        return _skip(CheckCode.PER_ITEM_LIMIT)
    amount = ctx.attempt.amount
    if amount > limit:
        return _fail(
            CheckCode.PER_ITEM_LIMIT,
            f"{amount} is over the {limit} per-item cap",
            amount=amount.minor,
            limit=limit.minor,
            over_by=(amount - limit).minor,
        )
    return _ok(
        CheckCode.PER_ITEM_LIMIT,
        f"{amount} is within the {limit} per-item cap",
        amount=amount.minor,
        limit=limit.minor,
    )


def check_structuring(ctx: Context) -> CheckResult:
    """Catch a cap that is being evaded by splitting rather than broken.

    An agent told "nothing over 100" and asked for a 150 item will often
    discover, entirely on its own, that two charges of 75 both pass. Each one
    is legitimate under the per-item check. Only the cluster is not.

    So the cap is enforced against the group of recent charges to the same
    counterparty, not against the charge in isolation. `confidence` is a
    heuristic, not a probability: amounts packed close under the cap and a
    longer cluster both read as more deliberate.
    """
    m = ctx.mandate
    limit = m.per_item_limit
    if limit is None:
        return _skip(CheckCode.STRUCTURING, "no per-item cap to evade")

    amount = ctx.attempt.amount
    if amount >= limit:
        # Over the cap outright. That is the per-item check's business, not a split.
        return _skip(CheckCode.STRUCTURING, "attempt is not below the cap")

    prior = ctx.cluster()
    if not prior:
        return _ok(CheckCode.STRUCTURING, "no recent charges to this counterparty")

    prior_total = Money.sum((c.amount for c in prior), ctx.currency)
    combined = prior_total + amount
    if combined <= limit:
        return _ok(
            CheckCode.STRUCTURING,
            f"{combined} across {len(prior) + 1} charges is still within {limit}",
            cluster_total=combined.minor,
            limit=limit.minor,
        )

    members = [*prior, None]  # None stands in for the attempt itself
    fills = [
        (c.amount.minor if c is not None else amount.minor) / limit.minor
        for c in members
    ]
    mean_fill = sum(fills) / len(fills)
    confidence = min(0.99, 0.5 + 0.4 * mean_fill + 0.1 * min(len(members) - 2, 5) / 5)

    return _fail(
        CheckCode.STRUCTURING,
        (
            f"{len(members)} charges to {ctx.target_group} totalling {combined} "
            f"inside {m.structuring_window_seconds}s, each one under the {limit} cap"
        ),
        group=ctx.target_group,
        window_seconds=m.structuring_window_seconds,
        cluster_size=len(members),
        cluster_total=combined.minor,
        limit=limit.minor,
        over_by=(combined - limit).minor,
        mean_fill=round(mean_fill, 4),
        confidence=round(confidence, 4),
        prior_charge_ids=[c.id for c in prior],
        prior_amounts=[c.amount.minor for c in prior],
    )


def check_per_payee(ctx: Context) -> CheckResult:
    limit = ctx.mandate.per_payee_limit
    if limit is None:
        return _skip(CheckCode.PER_PAYEE_LIMIT)
    group = ctx.target_group
    already = ctx.spent_on(group)
    projected = already + ctx.attempt.amount
    if projected > limit:
        return _fail(
            CheckCode.PER_PAYEE_LIMIT,
            f"{projected} to {group} would pass the {limit} cap for one counterparty",
            group=group,
            already=already.minor,
            projected=projected.minor,
            limit=limit.minor,
        )
    return _ok(
        CheckCode.PER_PAYEE_LIMIT,
        f"{projected} to {group} is within {limit}",
        group=group,
        projected=projected.minor,
        limit=limit.minor,
    )


def check_budget(ctx: Context) -> CheckResult:
    available = ctx.available
    amount = ctx.attempt.amount
    if amount > available:
        return _fail(
            CheckCode.INSUFFICIENT_BUDGET,
            f"{amount} exceeds the {available} left on this mandate",
            amount=amount.minor,
            available=available.minor,
            committed=ctx.committed.minor,
            total_limit=ctx.mandate.total_limit.minor,
        )
    return _ok(
        CheckCode.INSUFFICIENT_BUDGET,
        f"{available} available, {amount} requested",
        available=available.minor,
        committed=ctx.committed.minor,
    )


def check_velocity(ctx: Context) -> CheckResult:
    """How fast, not just how much. A correct budget spent in nine seconds is a loop."""
    v = ctx.mandate.velocity
    if v is None:
        return _skip(CheckCode.VELOCITY)

    recent = ctx.within(v.window_seconds)
    count = len(recent) + 1
    spend = Money.sum((c.amount for c in recent), ctx.currency) + ctx.attempt.amount

    evidence: dict[str, object] = {
        "window_seconds": v.window_seconds,
        "projected_count": count,
        "projected_amount": spend.minor,
        "max_count": v.max_count,
        "max_amount": v.max_amount.minor if v.max_amount else None,
    }

    if v.max_count is not None and count > v.max_count:
        return _fail(
            CheckCode.VELOCITY,
            f"{count} charges in {v.window_seconds}s, cap is {v.max_count}",
            **evidence,
        )
    if v.max_amount is not None and spend > v.max_amount:
        return _fail(
            CheckCode.VELOCITY,
            f"{spend} in {v.window_seconds}s, cap is {v.max_amount}",
            **evidence,
        )
    return _ok(CheckCode.VELOCITY, f"{count} charges in {v.window_seconds}s", **evidence)


def check_concentration(ctx: Context) -> CheckResult:
    """Stop the whole budget quietly ending up with one counterparty."""
    share = ctx.mandate.concentration_max_share
    if share is None:
        return _skip(CheckCode.CONCENTRATION)

    floor = ctx.mandate.concentration_floor
    if floor is not None and ctx.committed < floor:
        return _ok(
            CheckCode.CONCENTRATION,
            f"book is still under {floor}, too small to judge concentration on",
            committed=ctx.committed.minor,
            floor=floor.minor,
        )

    group = ctx.target_group
    amount = ctx.attempt.amount
    projected_group = ctx.spent_on(group) + amount
    projected_total = ctx.committed + amount
    if projected_total.minor == 0:
        return _ok(CheckCode.CONCENTRATION, "nothing committed yet")

    actual = Decimal(projected_group.minor) / Decimal(projected_total.minor)
    evidence: dict[str, object] = {
        "group": group,
        "projected_group": projected_group.minor,
        "projected_total": projected_total.minor,
        "share": float(round(actual, 4)),
        "max_share": share,
    }
    if actual > Decimal(str(share)):
        return _fail(
            CheckCode.CONCENTRATION,
            f"{actual:.0%} of spend would sit with {group}, cap is {share:.0%}",
            **evidence,
        )
    return _ok(CheckCode.CONCENTRATION, f"{actual:.0%} with {group}", **evidence)


#: Order is the order a human would ask the questions in: is this mandate real,
#: is this attempt in scope, and only then is the number acceptable.
CHECKS: tuple[tuple[CheckCode, Check], ...] = (
    (CheckCode.MANDATE_INACTIVE, check_mandate_active),
    (CheckCode.CURRENCY_MISMATCH, check_currency),
    (CheckCode.OUTSIDE_WINDOW, check_window),
    (CheckCode.PAYEE_NOT_ALLOWED, check_payee_allowed),
    (CheckCode.CATEGORY_NOT_ALLOWED, check_category_allowed),
    (CheckCode.PER_ITEM_LIMIT, check_per_item),
    (CheckCode.STRUCTURING, check_structuring),
    (CheckCode.PER_PAYEE_LIMIT, check_per_payee),
    (CheckCode.INSUFFICIENT_BUDGET, check_budget),
    (CheckCode.VELOCITY, check_velocity),
    (CheckCode.CONCENTRATION, check_concentration),
)

#: These weigh the attempt's amount against the mandate's. Across two
#: currencies that comparison has no meaning, so a mismatch stands them down
#: instead of letting an exception escape what is meant to be a pure function.
_NEEDS_COMPARABLE_AMOUNT: frozenset[CheckCode] = frozenset(
    {
        CheckCode.PER_ITEM_LIMIT,
        CheckCode.STRUCTURING,
        CheckCode.PER_PAYEE_LIMIT,
        CheckCode.INSUFFICIENT_BUDGET,
        CheckCode.VELOCITY,
        CheckCode.CONCENTRATION,
    }
)

#: Failures these codes raise cannot be fixed by asking for less money.
_AMOUNT_BLIND: frozenset[CheckCode] = frozenset(
    {
        CheckCode.MANDATE_INACTIVE,
        CheckCode.CURRENCY_MISMATCH,
        CheckCode.OUTSIDE_WINDOW,
        CheckCode.PAYEE_NOT_ALLOWED,
        CheckCode.CATEGORY_NOT_ALLOWED,
    }
)


@dataclass(frozen=True, slots=True)
class Decision:
    """A verdict, every rule that produced it, and what would have cleared."""

    verdict: Verdict
    attempt: Attempt
    mandate_id: str
    evaluated_at: datetime
    trace: tuple[CheckResult, ...]
    available: Money
    max_allowable: Money

    @property
    def allowed(self) -> bool:
        return self.verdict is Verdict.ALLOW

    @property
    def remaining_after(self) -> Money:
        """Budget left once this attempt's hold is placed.

        `available` is the balance the checks were run against, which on an
        allow is the balance before the hold. A person reading the decision
        wants the one after it.
        """
        if not self.allowed:
            return self.available
        return (self.available - self.attempt.amount).clamped()

    @property
    def failures(self) -> tuple[CheckResult, ...]:
        """Failed checks, worst first, ties broken by the order they ran in."""
        indexed = [(i, r) for i, r in enumerate(self.trace) if r.failed]
        indexed.sort(key=lambda pair: (-pair[1].severity.value, pair[0]))
        return tuple(r for _, r in indexed)

    @property
    def headline(self) -> CheckResult | None:
        failures = self.failures
        return failures[0] if failures else None

    def reason(self) -> str:
        """One sentence, for a human, for the grid, and for the narration."""
        head = self.headline
        if head is None:
            return f"Allowed. {self.remaining_after} left on this mandate."
        extra = len(self.failures) - 1
        tail = f" (+{extra} more)" if extra else ""
        return f"Blocked, {head.code.value}: {head.detail}{tail}"

    def to_dict(self) -> dict[str, object]:
        return {
            "attempt_id": self.attempt.id,
            "mandate_id": self.mandate_id,
            "verdict": self.verdict.value,
            "evaluated_at": self.evaluated_at.isoformat(),
            "reason": self.reason(),
            "amount": self.attempt.amount.minor,
            "currency": self.attempt.amount.currency,
            "payee": self.attempt.payee,
            "category": self.attempt.category,
            "available": self.available.minor,
            "remaining_after": self.remaining_after.minor,
            "max_allowable": self.max_allowable.minor,
            "failed_codes": [r.code.value for r in self.failures],
            "trace": [r.to_dict() for r in self.trace],
        }


def _headroom(ctx: Context, trace: Sequence[CheckResult]) -> Money:
    """The largest amount that would have cleared everything, right now.

    Worth computing even on an allow: it is what turns "blocked" into "blocked,
    but 4,200 would have gone through", which is the difference between a wall
    and a boundary.
    """
    currency = ctx.currency
    zero = Money.zero(currency)

    for result in trace:
        if result.failed and result.code in _AMOUNT_BLIND:
            return zero

    m = ctx.mandate
    caps: list[Money] = [m.total_limit - ctx.committed]

    if m.per_item_limit is not None:
        caps.append(m.per_item_limit)
        prior = ctx.cluster()
        if prior:
            prior_total = Money.sum((c.amount for c in prior), currency)
            # Anything above this folds the cluster over the cap.
            caps.append(m.per_item_limit - prior_total)

    if m.per_payee_limit is not None:
        caps.append(m.per_payee_limit - ctx.spent_on(ctx.target_group))

    v = m.velocity
    if v is not None:
        recent = ctx.within(v.window_seconds)
        if v.max_count is not None and len(recent) + 1 > v.max_count:
            return zero
        if v.max_amount is not None:
            spent = Money.sum((c.amount for c in recent), currency)
            caps.append(v.max_amount - spent)

    share = m.concentration_max_share
    floor = m.concentration_floor
    judged = floor is None or ctx.committed >= floor
    if share is not None and share < 1 and judged:
        # group + x <= share * (total + x)  ->  x <= (share*total - group) / (1 - share)
        ratio = Decimal(str(share))
        total = Decimal(ctx.committed.minor)
        group = Decimal(ctx.spent_on(ctx.target_group).minor)
        numerator = ratio * total - group
        caps.append(Money(int(numerator / (Decimal(1) - ratio)), currency))

    return min(caps).clamped()


def evaluate(
    mandate: Mandate,
    attempt: Attempt,
    history: Iterable[Charge] = (),
    *,
    now: datetime | None = None,
    directory: PayeeDirectory | None = None,
) -> Decision:
    """Decide whether `attempt` is within `mandate`, given what has happened."""
    if attempt.mandate_id != mandate.id:
        raise ValueError(
            f"attempt {attempt.id} is for mandate {attempt.mandate_id}, not {mandate.id}"
        )

    ctx = Context(
        mandate=mandate,
        attempt=attempt,
        history=tuple(c for c in history if c.mandate_id == mandate.id),
        now=now or attempt.requested_at,
        directory=directory or PayeeDirectory(),
    )

    trace: list[CheckResult] = []
    comparable = True
    for code, check in CHECKS:
        if not comparable and code in _NEEDS_COMPARABLE_AMOUNT:
            trace.append(_skip(code, "amount is not comparable to this mandate"))
            continue
        result = check(ctx)
        if code is CheckCode.CURRENCY_MISMATCH and result.failed:
            comparable = False
        trace.append(result)

    blocked = any(r.failed for r in trace)

    return Decision(
        verdict=Verdict.BLOCK if blocked else Verdict.ALLOW,
        attempt=attempt,
        mandate_id=mandate.id,
        evaluated_at=ctx.now,
        trace=tuple(trace),
        available=ctx.available,
        max_allowable=_headroom(ctx, trace),
    )
