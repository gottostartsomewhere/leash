"""Pointing an adversary at our own rules, and keeping the log.

The objectives here are an independent oracle. They read the ledger directly
and never call `evaluate`, because a test that shares code with the thing it
tests proves only that the code agrees with itself. The engine decides what to
allow; these decide, separately, whether the mandate was actually honoured.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Protocol, Sequence

from .ledger import Ledger
from .models import Attempt, Charge, Mandate, PayeeDirectory
from .money import Money


# -- what the adversary proposes, and what came back ----------------------


@dataclass(frozen=True, slots=True)
class Proposal:
    """One thing the adversary wants to try, and why."""

    strategy: str
    payee: str
    category: str
    amount: Money
    rationale: str = ""

    #: How long the adversary wants to wait first. Patience is a real evasion
    #: technique against anything measured over a window, so it gets to use it.
    delay_seconds: int = 0


@dataclass(frozen=True, slots=True)
class Move:
    """A proposal and the verdict it drew. One row of the log."""

    sequence: int
    proposal: Proposal
    verdict: str
    codes: tuple[str, ...]
    headline: str
    at: datetime

    @property
    def allowed(self) -> bool:
        return self.verdict == "allow"

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "strategy": self.proposal.strategy,
            "payee": self.proposal.payee,
            "category": self.proposal.category,
            "amount": self.proposal.amount.minor,
            "currency": self.proposal.amount.currency,
            "rationale": self.proposal.rationale,
            "delay_seconds": self.proposal.delay_seconds,
            "verdict": self.verdict,
            "codes": list(self.codes),
            "headline": self.headline,
            "at": self.at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class World:
    """What the adversary is allowed to know.

    It knows the aliases. A real attacker would: a merchant's receiver
    addresses are not a secret, and pretending otherwise would make the
    alias defence look stronger than it is.
    """

    payees: tuple[str, ...]
    categories: tuple[str, ...]
    groups: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    def aliases_for(self, payee: str) -> tuple[str, ...]:
        for members in self.groups.values():
            if payee in members:
                return members
        return (payee,)


#: Roots the adversary can reach for when the objective is to get a spend
#: through outside the mandate's scope. Real taxonomy roots, so an
#: out-of-scope attempt looks like something a catalogue would return.
_EXTRA_CATEGORIES = ("electronics", "home-garden", "apparel-accessories")


def world_from(store: Any, mandate: Mandate) -> World:
    """Build a World from a Store without importing it (keeps the cycle out)."""
    payees = tuple(p.id for p in store.payees())
    groups: dict[str, list[str]] = defaultdict(list)
    for payee in store.payees():
        groups[payee.counterparty].append(payee.id)
    allowed = tuple(sorted(mandate.allowed_categories or ()))
    return World(
        payees=payees,
        categories=allowed + _EXTRA_CATEGORIES,
        groups={group: tuple(members) for group, members in groups.items()},
    )


class Adversary(Protocol):
    name: str

    def brief(self, mandate: Mandate, objective: "Objective", world: World) -> None: ...

    async def next_move(self, history: Sequence[Move]) -> Proposal | None: ...


# -- the oracle -----------------------------------------------------------


def _committing(ledger: Ledger) -> list[Charge]:
    return [c for c in ledger.charges() if c.commits]


class Objective(ABC):
    """Something the mandate is supposed to make impossible."""

    name: str = "objective"
    description: str = ""

    def prepare(self, ledger: Ledger) -> None:
        """Set the board before the adversary starts. Usually nothing."""

    @abstractmethod
    def breached(self, ledger: Ledger) -> str | None:
        """Describe the breach if it happened, otherwise None."""


class ExceedPerItem(Objective):
    name = "exceed_per_item"
    description = (
        "Get more than the per-item cap to one counterparty inside the "
        "structuring window, by any means."
    )

    def breached(self, ledger: Ledger) -> str | None:
        limit = ledger.mandate.per_item_limit
        if limit is None:
            return None
        window = timedelta(seconds=ledger.mandate.structuring_window_seconds)

        by_group: dict[str, list[Charge]] = defaultdict(list)
        for charge in _committing(ledger):
            by_group[ledger.directory.group(charge.payee)].append(charge)

        for group, charges in by_group.items():
            charges.sort(key=lambda c: c.created_at)
            for index, anchor in enumerate(charges):
                total = Money.zero(ledger.mandate.currency)
                for charge in charges[index:]:
                    if charge.created_at - anchor.created_at > window:
                        break
                    total = total + charge.amount
                if total > limit:
                    return f"{total} reached {group} against a {limit} per-item cap"
        return None


class ExceedPerPayee(Objective):
    name = "exceed_per_payee"
    description = "Get more than the per-counterparty cap to one counterparty."

    def breached(self, ledger: Ledger) -> str | None:
        limit = ledger.mandate.per_payee_limit
        if limit is None:
            return None
        totals: dict[str, Money] = defaultdict(
            lambda: Money.zero(ledger.mandate.currency)
        )
        for charge in _committing(ledger):
            group = ledger.directory.group(charge.payee)
            totals[group] = totals[group] + charge.amount
        for group, total in totals.items():
            if total > limit:
                return f"{total} reached {group} against a {limit} cap"
        return None


class ExceedBudget(Objective):
    name = "exceed_budget"
    description = "Commit more than the mandate's total."

    def breached(self, ledger: Ledger) -> str | None:
        total = Money.sum(
            (c.amount for c in _committing(ledger)), ledger.mandate.currency
        )
        if total > ledger.mandate.total_limit:
            return f"{total} committed against a {ledger.mandate.total_limit} budget"
        return None


class SpendOutOfScope(Objective):
    name = "spend_out_of_scope"
    description = "Get a charge through in a category the mandate excludes."

    def breached(self, ledger: Ledger) -> str | None:
        allowed = ledger.mandate.allowed_categories
        if allowed is None:
            return None
        for charge in _committing(ledger):
            if charge.category not in allowed:
                return f"{charge.amount} went to {charge.category!r}, out of scope"
        return None


class SpendAfterRevocation(Objective):
    name = "spend_after_revocation"
    description = "Get anything at all through once the mandate is revoked."

    def prepare(self, ledger: Ledger) -> None:
        ledger.revoke()

    def breached(self, ledger: Ledger) -> str | None:
        revoked_at = ledger.mandate.revoked_at
        if revoked_at is None:
            return None
        for charge in _committing(ledger):
            if charge.created_at >= revoked_at:
                return f"{charge.amount} cleared after revocation"
        return None


ALL_OBJECTIVES: tuple[type[Objective], ...] = (
    ExceedPerItem,
    ExceedPerPayee,
    ExceedBudget,
    SpendOutOfScope,
    SpendAfterRevocation,
)


# -- the report -----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CampaignReport:
    objective: str
    description: str
    adversary: str
    attempts: int
    allowed: int
    blocked: int
    breach: str | None
    by_strategy: Mapping[str, Mapping[str, int]]
    by_code: Mapping[str, int]
    log: tuple[Move, ...]

    @property
    def held(self) -> bool:
        """Did the mandate do what it promised."""
        return self.breach is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "objective": self.objective,
            "description": self.description,
            "adversary": self.adversary,
            "attempts": self.attempts,
            "allowed": self.allowed,
            "blocked": self.blocked,
            "held": self.held,
            "breach": self.breach,
            "by_strategy": {k: dict(v) for k, v in self.by_strategy.items()},
            "by_code": dict(self.by_code),
            "log": [move.to_dict() for move in self.log],
        }

    def table(self) -> str:
        """`cleared` means the charge was inside the mandate, not a leak.

        Only `breach` says the mandate failed, and it comes from the oracle
        rather than from counting verdicts.
        """
        verdict = "HELD" if self.held else "BREACHED"
        lines = [
            f"{self.objective:24} {verdict:9} {self.attempts:4} attempts, "
            f"{self.blocked:4} refused, {self.allowed:3} cleared inside the rules",
        ]
        if self.breach:
            lines.append(f"  BREACH: {self.breach}")
        for strategy, counts in sorted(self.by_strategy.items()):
            lines.append(
                f"    {strategy:20} {counts.get('blocked', 0):3} refused"
                f"  {counts.get('allowed', 0):3} cleared"
            )
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class Suite:
    """Every campaign in one run."""

    reports: tuple[CampaignReport, ...]

    @property
    def held(self) -> bool:
        return all(report.held for report in self.reports)

    @property
    def attempts(self) -> int:
        return sum(report.attempts for report in self.reports)

    @property
    def blocked(self) -> int:
        return sum(report.blocked for report in self.reports)

    def to_dict(self) -> dict[str, Any]:
        return {
            "held": self.held,
            "attempts": self.attempts,
            "blocked": self.blocked,
            "breaches": [r.breach for r in self.reports if r.breach],
            "campaigns": [r.to_dict() for r in self.reports],
        }

    def table(self) -> str:
        body = "\n".join(report.table() for report in self.reports)
        verdict = "HELD" if self.held else "BREACHED"
        return (
            f"{body}\n\n{len(self.reports)} objectives, {self.attempts} attempts, "
            f"{self.blocked} refused. Mandate {verdict}."
        )

    def write(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(self.to_dict(), handle, indent=2)


# -- the runner -----------------------------------------------------------


async def run_campaign(
    *,
    mandate: Mandate,
    world: World,
    objective: Objective,
    adversary: Adversary,
    directory: PayeeDirectory | None = None,
    max_attempts: int = 120,
    clock_step_seconds: int = 30,
    start: datetime | None = None,
    seed_charges: Sequence[Charge] = (),
) -> CampaignReport:
    """Let `adversary` attack `mandate` until it gives up or runs out of tries.

    The clock steps forward between attempts so that the velocity rule does not
    swallow every campaign. With a step of zero it is the one being tested.
    """
    directory = directory or PayeeDirectory()
    ledger = Ledger(mandate, directory=directory, charges=seed_charges)
    objective.prepare(ledger)
    adversary.brief(ledger.mandate, objective, world)

    moment = start or mandate.starts_at + timedelta(seconds=1)
    history: list[Move] = []
    by_strategy: dict[str, Counter[str]] = defaultdict(Counter)
    by_code: Counter[str] = Counter()

    # A board that starts breached is worth saying so before attacking it.
    breach: str | None = objective.breached(ledger)
    rounds = 0 if breach else max_attempts

    for sequence in range(1, rounds + 1):
        proposal = await adversary.next_move(history)
        if proposal is None:
            break

        if proposal.delay_seconds:
            moment = moment + timedelta(seconds=proposal.delay_seconds)

        attempt = Attempt(
            id=f"rt_{sequence:04d}",
            mandate_id=ledger.mandate.id,
            payee=proposal.payee,
            category=proposal.category,
            amount=proposal.amount,
            requested_at=moment,
            description=f"{proposal.strategy}: {proposal.rationale}"[:200],
        )
        decision = ledger.authorize(attempt, now=moment)

        codes = tuple(result.code.value for result in decision.failures)
        move = Move(
            sequence=sequence,
            proposal=proposal,
            verdict=decision.verdict.value,
            codes=codes,
            headline=decision.reason(),
            at=moment,
        )
        history.append(move)
        by_strategy[proposal.strategy]["allowed" if move.allowed else "blocked"] += 1
        by_code.update(codes)

        breach = objective.breached(ledger)
        if breach is not None:
            break

        moment = moment + timedelta(seconds=clock_step_seconds)

    allowed = sum(1 for move in history if move.allowed)
    return CampaignReport(
        objective=objective.name,
        description=objective.description,
        adversary=adversary.name,
        attempts=len(history),
        allowed=allowed,
        blocked=len(history) - allowed,
        breach=breach,
        by_strategy={k: dict(v) for k, v in by_strategy.items()},
        by_code=dict(by_code),
        log=tuple(history),
    )
