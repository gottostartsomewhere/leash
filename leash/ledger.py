"""Authorize, hold, settle.

The hold is the point. An agent that gets an allow has not spent anything yet,
it has reserved budget, and that reservation counts against every later check
until it is captured or released. Without it, two attempts evaluated a
millisecond apart both see the full balance and both pass.
"""

from __future__ import annotations

import threading
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

        # Every read and every write goes through this.
        #
        # The hold above only works if deciding and holding happen as one
        # step. The API serves `authorize` from a thread pool, and without a
        # lock two threads could both evaluate against the same charges and
        # both write a hold: thirty-two retries of one idempotency key made
        # thirty-two holds, and a burst cleared seven charges through a pace
        # limit of six. Reads are locked too, because iterating the charges
        # while another thread inserts one raises rather than returning a
        # stale answer. Reentrant, because summary() reads committed and
        # revoke() calls release().
        self._lock = threading.RLock()

        # Holds a payout has claimed and is waiting on the processor for.
        # Still PENDING and still counting against the budget, but they
        # cannot be claimed again, released, or dropped by a revocation
        # until that payout resolves them. See claim().
        self._in_flight: set[str] = set()

    # -- state -----------------------------------------------------------

    @property
    def mandate(self) -> Mandate:
        return self._mandate

    @property
    def directory(self) -> PayeeDirectory:
        return self._directory

    def charges(self) -> tuple[Charge, ...]:
        with self._lock:
            return tuple(self._charges.values())

    def decisions(self) -> tuple[Decision, ...]:
        with self._lock:
            return tuple(self._decisions)

    def charge(self, charge_id: str) -> Charge:
        with self._lock:
            try:
                return self._charges[charge_id]
            except KeyError:
                raise UnknownCharge(charge_id) from None

    @property
    def committed(self) -> Money:
        with self._lock:
            return Money.sum(
                (c.amount for c in self._charges.values() if c.commits),
                self._mandate.currency,
            )

    @property
    def available(self) -> Money:
        with self._lock:
            return (self._mandate.total_limit - self.committed).clamped()

    @property
    def held(self) -> Money:
        with self._lock:
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
        with self._lock:
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

    # -- payouts ---------------------------------------------------------

    def claim(self, charge_ids: Iterable[str]) -> tuple[Charge, ...]:
        """Reserve pending holds for a payout that is about to go out.

        Taken before the processor is called, because the call is the slow
        part. The payout used to check each charge was PENDING, await PayPal,
        and only then mark it settled, so a second request landing inside
        that second passed the same check and the same charges were sent to
        PayPal twice. The second request only found out when settling failed,
        by which point the money had gone. Claiming is atomic, so the second
        request is refused here, before anything leaves.

        Duplicates in one request are collapsed rather than paid twice.
        All or nothing: if any charge cannot be claimed, none is.
        """
        ids = list(dict.fromkeys(charge_ids))
        with self._lock:
            claimed = []
            for charge_id in ids:
                charge = self.charge(charge_id)
                if charge.state is not ChargeState.PENDING:
                    raise IllegalTransition(
                        f"{charge_id} is {charge.state.value}, not a pending hold"
                    )
                if charge_id in self._in_flight:
                    raise IllegalTransition(f"{charge_id} is already being paid out")
                claimed.append(charge)
            self._in_flight.update(ids)
            return tuple(claimed)

    def unclaim(self, charge_ids: Iterable[str]) -> None:
        """Hand claimed holds back, once the payout holding them is done."""
        with self._lock:
            self._in_flight.difference_update(charge_ids)

    def in_flight(self, charge_id: str) -> bool:
        with self._lock:
            return charge_id in self._in_flight

    # -- lifecycle -------------------------------------------------------

    def _move(
        self,
        charge_id: str,
        to: ChargeState,
        *,
        amount: Money | None = None,
    ) -> Charge:
        with self._lock:
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
        with self._lock:
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
        """Void a hold and give the budget back.

        Not while a payout has it. The processor may already be moving that
        money, and handing the budget back for a charge that is about to
        settle would let the mandate spend it twice.
        """
        with self._lock:
            if charge_id in self._in_flight:
                raise IllegalTransition(
                    f"{charge_id} is being paid out and cannot be released"
                )
            return self._move(charge_id, ChargeState.RELEASED)

    def fail(self, charge_id: str) -> Charge:
        """The processor rejected it. Budget comes back, same as a release."""
        return self._move(charge_id, ChargeState.FAILED)

    def reverse(self, charge_id: str) -> Charge:
        """A settled payout came back. The budget returns with it.

        The only transition out of SETTLED, and it exists because settling is
        a decision made on incomplete information. A processor accepts a batch
        before it knows whether each item will land, so a charge can be
        truthfully settled at one moment and wrong about it an hour later.
        The alternative is a ledger that records what we intended rather than
        what happened, which is the thing this project is arguing against.
        """
        with self._lock:
            charge = self.charge(charge_id)
            if charge.state is not ChargeState.SETTLED:
                raise IllegalTransition(
                    f"{charge_id} is {charge.state.value}, only a settled charge can come back"
                )
            moved = charge.with_state(ChargeState.FAILED)
            self._charges[charge_id] = moved
            return moved

    def revoke(self, *, at: datetime | None = None) -> tuple[Charge, ...]:
        """Kill the mandate and drop every hold that has not been captured.

        Settled charges stay settled. Revocation stops what has not happened;
        it does not claw back what has. A hold a payout has already claimed
        is left to that payout: the money may be moving as this runs, and it
        will settle or fail on its own when the processor answers.
        """
        with self._lock:
            moment = at or _utcnow()
            self._mandate = self._mandate.revoked(moment)
            dropped = [
                self.release(c.id)
                for c in list(self._charges.values())
                if c.state is ChargeState.PENDING and c.id not in self._in_flight
            ]
            return tuple(dropped)

    # -- presentation ----------------------------------------------------

    def rows(self) -> list[Mapping[str, object]]:
        """Every decision, newest last, shaped for the audit grid."""
        with self._lock:
            return [d.to_dict() for d in self._decisions]

    def summary(self) -> Mapping[str, object]:
        with self._lock:
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
