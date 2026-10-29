"""Authorize, hold, settle.

The hold is the point. An agent that gets an allow has not spent anything yet,
it has reserved budget, and that reservation counts against every later check
until it is captured or released. Without it, two attempts evaluated a
millisecond apart both see the full balance and both pass.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Mapping

from .engine import Decision, evaluate
from .models import (
    Attempt,
    Charge,
    ChargeState,
    Mandate,
    PayeeDirectory,
)
from .money import Money


class LedgerError(RuntimeError):
    """Base for things the ledger refuses to do."""


class UnknownCharge(LedgerError):
    pass


class IllegalTransition(LedgerError):
    pass


class OverCapture(LedgerError):
    """Capturing more than was authorized. Processors reject this; so do we."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Ledger:
    """One mandate's money, and every decision taken against it."""

    def __init__(
        self,
        mandate: Mandate,
        *,
        directory: PayeeDirectory | None = None,
        charges: Iterable[Charge] = (),
    ) -> None:
        self._mandate = mandate
        self._directory = directory or PayeeDirectory()
        self._charges: dict[str, Charge] = {c.id: c for c in charges}
        self._decisions: list[Decision] = []
        self._by_key: dict[str, str] = {}
        self._by_attempt: dict[str, Decision] = {}

    # -- state -----------------------------------------------------------

    @property
    def mandate(self) -> Mandate:
        return self._mandate

    @property
    def directory(self) -> PayeeDirectory:
        return self._directory

    def charges(self) -> tuple[Charge, ...]:
        return tuple(self._charges.values())

    def decisions(self) -> tuple[Decision, ...]:
        return tuple(self._decisions)

    def charge(self, charge_id: str) -> Charge:
        try:
            return self._charges[charge_id]
        except KeyError:
            raise UnknownCharge(charge_id) from None

    @property
    def committed(self) -> Money:
        return Money.sum(
            (c.amount for c in self._charges.values() if c.commits),
            self._mandate.currency,
        )

    @property
    def available(self) -> Money:
        return (self._mandate.total_limit - self.committed).clamped()

    @property
    def held(self) -> Money:
        return Money.sum(
            (
                c.amount
                for c in self._charges.values()
                if c.state is ChargeState.PENDING
            ),
            self._mandate.currency,
        )

    # -- authorization ---------------------------------------------------

    def authorize(self, attempt: Attempt, *, now: datetime | None = None) -> Decision:
        """Evaluate `attempt` and, if it clears, hold the money.

        Replaying the same idempotency key returns the original decision and
        creates nothing. An agent that retries a timeout should not end up
        holding the budget twice.
        """
        key = attempt.idempotency_key
        if key is not None and key in self._by_key:
            return self._by_attempt[self._by_key[key]]

        decision = evaluate(
            self._mandate,
            attempt,
            self._charges.values(),
            now=now,
            directory=self._directory,
        )

        if decision.allowed:
            charge = Charge(
                id=f"chg_{attempt.id}",
                mandate_id=self._mandate.id,
                payee=attempt.payee,
                category=attempt.category,
                amount=attempt.amount,
                created_at=decision.evaluated_at,
                state=ChargeState.PENDING,
                description=attempt.description,
                attempt_id=attempt.id,
            )
            self._charges[charge.id] = charge

        self._decisions.append(decision)
        self._by_attempt[attempt.id] = decision
        if key is not None:
            self._by_key[key] = attempt.id
        return decision

    # -- lifecycle -------------------------------------------------------

    def _move(
        self,
        charge_id: str,
        to: ChargeState,
        *,
        amount: Money | None = None,
    ) -> Charge:
        charge = self.charge(charge_id)
        if charge.state is not ChargeState.PENDING:
            raise IllegalTransition(
                f"{charge_id} is {charge.state.value}, only a pending hold can move"
            )
        moved = charge.with_state(to, amount)
        self._charges[charge_id] = moved
        return moved

    def settle(self, charge_id: str, amount: Money | None = None) -> Charge:
        """Capture a hold, optionally for less than was authorized."""
        charge = self.charge(charge_id)
        if amount is not None:
            if amount.currency != charge.amount.currency:
                raise OverCapture("capture currency does not match the hold")
            if amount > charge.amount:
                raise OverCapture(
                    f"cannot capture {amount} against a {charge.amount} hold"
                )
        return self._move(charge_id, ChargeState.SETTLED, amount=amount)

    def release(self, charge_id: str) -> Charge:
        """Void a hold and give the budget back."""
        return self._move(charge_id, ChargeState.RELEASED)

    def fail(self, charge_id: str) -> Charge:
        """The processor rejected it. Budget comes back, same as a release."""
        return self._move(charge_id, ChargeState.FAILED)

    def revoke(self, *, at: datetime | None = None) -> tuple[Charge, ...]:
        """Kill the mandate and drop every hold that has not been captured.

        Settled charges stay settled. Revocation stops what has not happened;
        it does not claw back what has.
        """
        moment = at or _utcnow()
        self._mandate = self._mandate.revoked(moment)
        dropped = [
            self.release(c.id)
            for c in list(self._charges.values())
            if c.state is ChargeState.PENDING
        ]
        return tuple(dropped)

    # -- presentation ----------------------------------------------------

    def rows(self) -> list[Mapping[str, object]]:
        """Every decision, newest last, shaped for the audit grid."""
        return [d.to_dict() for d in self._decisions]

    def summary(self) -> Mapping[str, object]:
        return {
            "mandate_id": self._mandate.id,
            "agent_id": self._mandate.agent_id,
            "status": self._mandate.status.value,
            "currency": self._mandate.currency,
            "total_limit": self._mandate.total_limit.minor,
            "committed": self.committed.minor,
            "held": self.held.minor,
            "available": self.available.minor,
            "attempts": len(self._decisions),
            "blocked": sum(1 for d in self._decisions if not d.allowed),
        }
