"""The agent that is supposed to behave.

It works a list and takes no for an answer. When a spend is refused it reads
`max_allowable` off the decision and asks again for what would actually clear,
which is the whole point of reporting a boundary instead of a wall.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Sequence

from .engine import Decision
from .ledger import Ledger
from .models import Attempt
from .money import Money


@dataclass(frozen=True, slots=True)
class LineItem:
    """Something the agent has been sent to buy."""

    label: str
    payee: str
    category: str
    amount: Money


@dataclass(frozen=True, slots=True)
class Step:
    """One line of the agent's working."""

    item: LineItem
    decision: Decision
    action: str  # bought | trimmed | abandoned

    def summary(self) -> str:
        asked = self.item.amount
        got = self.decision.attempt.amount
        if self.action == "trimmed":
            return f"{self.item.label}: asked {asked}, took {got}"
        if self.action == "bought":
            return f"{self.item.label}: {got}"
        return f"{self.item.label}: gave up on {asked}, {self.decision.reason()}"


class ProcurementAgent:
    """Spends against a mandate, politely."""

    name = "procurement"

    def __init__(
        self,
        ledger: Ledger,
        *,
        trim_to_allowable: bool = True,
        pace_seconds: int = 0,
    ) -> None:
        self._ledger = ledger
        self._trim = trim_to_allowable
        self._pace = pace_seconds

    def run(
        self, items: Iterable[LineItem], *, start: datetime | None = None
    ) -> list[Step]:
        moment = start or datetime.now(timezone.utc)
        steps: list[Step] = []

        for index, item in enumerate(items, start=1):
            decision = self._ask(item, item.amount, f"buy_{index:03d}", moment)

            if decision.allowed:
                steps.append(Step(item, decision, "bought"))
            elif self._trim and decision.max_allowable.minor > 0:
                # It was told what would clear. Take that rather than nothing.
                retry = self._ask(
                    item, decision.max_allowable, f"buy_{index:03d}r", moment
                )
                steps.append(
                    Step(item, retry, "trimmed" if retry.allowed else "abandoned")
                )
            else:
                steps.append(Step(item, decision, "abandoned"))

            moment = moment + timedelta(seconds=self._pace)

        return steps

    def _ask(
        self, item: LineItem, amount: Money, attempt_id: str, moment: datetime
    ) -> Decision:
        attempt = Attempt(
            id=attempt_id,
            mandate_id=self._ledger.mandate.id,
            payee=item.payee,
            category=item.category,
            amount=amount,
            requested_at=moment,
            description=item.label,
        )
        return self._ledger.authorize(attempt, now=moment)


def spent(steps: Sequence[Step]) -> int:
    """Minor units actually held, across every step that cleared."""
    return sum(s.decision.attempt.amount.minor for s in steps if s.decision.allowed)
