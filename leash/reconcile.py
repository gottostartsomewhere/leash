"""Ask the processor what actually happened, and correct the ledger.

Settling is a decision made on incomplete information. PayPal accepts a batch
and returns PENDING long before it knows whether each item will land, and we
settle on that, because at that point the instruction has been accepted and
the budget really is gone. But an item can turn into RETURNED or FAILED an
hour later, and nothing comes back to tell us.

Without this, the grid would keep saying a payment settled while the money sat
back in the sender's account. That is precisely the failure this whole project
argues against: a ledger that records what we intended instead of what
happened. So reconciliation re-reads a batch and moves the ledger to match.

It corrects in both directions, and the two directions are not symmetric:

- The processor says the money came back and we think it settled. We can fix
  that ourselves, and we do. Budget returns.
- The processor says the money went and we think it did not. We report it and
  change nothing, because re-committing budget that has since been spent
  elsewhere could take the mandate over its own limit. A person needs to look
  at that one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .ledger import IllegalTransition, Ledger
from .models import Charge, ChargeState
from .payouts import PayoutGateway, PayoutResult, holds_money
from .store import NotFound, Store


@dataclass(frozen=True, slots=True)
class Correction:
    """One charge whose state did not match the processor."""

    charge_id: str
    was: str
    now: str
    processor_status: str
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "charge_id": self.charge_id,
            "was": self.was,
            "now": self.now,
            "processor_status": self.processor_status,
            "note": self.note,
        }


@dataclass(frozen=True, slots=True)
class ReconcileReport:
    batch_id: str
    status: str
    gateway: str
    checked: int = 0
    agreed: int = 0
    corrected: tuple[Correction, ...] = ()
    conflicts: tuple[Correction, ...] = ()
    unknown: tuple[str, ...] = ()

    @property
    def clean(self) -> bool:
        """Did the ledger already match the processor in every respect."""
        return not self.corrected and not self.conflicts and not self.unknown

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "status": self.status,
            "gateway": self.gateway,
            "checked": self.checked,
            "agreed": self.agreed,
            "clean": self.clean,
            "corrected": [c.to_dict() for c in self.corrected],
            "conflicts": [c.to_dict() for c in self.conflicts],
            "unknown": list(self.unknown),
        }

    def summary(self) -> str:
        if self.clean:
            return f"{self.batch_id}: {self.checked} items, the ledger already agreed"
        parts = [f"{self.batch_id}: {self.checked} items"]
        if self.corrected:
            parts.append(f"{len(self.corrected)} corrected")
        if self.conflicts:
            parts.append(f"{len(self.conflicts)} need a person")
        if self.unknown:
            parts.append(f"{len(self.unknown)} unrecognised")
        return ", ".join(parts)


def _apply(
    ledger: Ledger, charge: Charge, status: str
) -> tuple[Correction | None, Correction | None]:
    """Move one charge to match `status`. Returns (correction, conflict)."""
    was = charge.state.value

    if holds_money(status):
        if charge.state is ChargeState.SETTLED:
            return None, None
        if charge.state is ChargeState.PENDING:
            # We never recorded the capture, but the money went. Catch up.
            ledger.settle(charge.id)
            return (
                Correction(charge.id, was, "settled", status,
                           "the money moved but the hold was never captured"),
                None,
            )
        # Released or failed, yet the processor says it paid. Re-committing
        # budget that may since have been spent could push the mandate past
        # its own limit, so this one gets reported, not fixed.
        return None, Correction(
            charge.id, was, was, status,
            "the processor says this paid but the ledger gave the budget back",
        )

    if charge.state is ChargeState.SETTLED:
        ledger.reverse(charge.id)
        return (
            Correction(charge.id, was, "failed", status,
                       "settled on acceptance, but the payout came back"),
            None,
        )
    if charge.state is ChargeState.PENDING:
        try:
            ledger.fail(charge.id)
        except IllegalTransition:  # pragma: no cover - guarded above
            return None, None
        return Correction(charge.id, was, "failed", status), None

    return None, None


async def reconcile_batch(
    store: Store, gateway: PayoutGateway, batch_id: str
) -> ReconcileReport:
    """Re-read `batch_id` and move the ledger to match what it says."""
    result: PayoutResult = await gateway.status(batch_id)
    store.record_batch(result)

    corrected: list[Correction] = []
    conflicts: list[Correction] = []
    unknown: list[str] = []
    agreed = 0

    for item in result.items:
        try:
            ledger, charge = store.locate_charge(item.charge_id)
        except NotFound:
            # A batch can name a charge this process has never seen, after a
            # demo reset or a restart. Worth saying so rather than ignoring.
            unknown.append(item.charge_id)
            continue

        correction, conflict = _apply(ledger, charge, item.status)
        if correction is not None:
            corrected.append(correction)
        elif conflict is not None:
            conflicts.append(conflict)
        else:
            agreed += 1

    return ReconcileReport(
        batch_id=result.batch_id,
        status=result.status,
        gateway=result.gateway,
        checked=len(result.items),
        agreed=agreed,
        corrected=tuple(corrected),
        conflicts=tuple(conflicts),
        unknown=tuple(unknown),
    )


async def reconcile_all(
    store: Store, gateway: PayoutGateway
) -> tuple[ReconcileReport, ...]:
    """Every batch this process has sent, re-checked against the processor."""
    reports: list[ReconcileReport] = []
    for batch in store.batches():
        reports.append(await reconcile_batch(store, gateway, batch.batch_id))
    return tuple(reports)
