"""In-process state: mandates, their ledgers, the payee book, and batches.

Deliberately in memory. The demo needs a reset button that works in under a
second and a deployment with no database attached, and nothing here outlives
a run that a seed cannot rebuild.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Mapping

from .config import Settings, settings as default_settings
from .ledger import Ledger
from .models import Charge, Mandate, PayeeDirectory, Velocity
from .money import Money
from .payouts import PayoutResult


class NotFound(KeyError):
    """No mandate, charge or batch under that id."""


@dataclass(frozen=True, slots=True)
class Payee:
    """Somewhere money can go, and the counterparty actually behind it."""

    id: str
    name: str
    email: str
    group: str | None = None

    @property
    def counterparty(self) -> str:
        return self.group or self.id


def new_batch_id() -> str:
    """PayPal requires a unique sender_batch_id, and means it."""
    return f"leash_{uuid.uuid4().hex[:16]}"


class Store:
    def __init__(self) -> None:
        self._ledgers: dict[str, Ledger] = {}
        self._payees: dict[str, Payee] = {}
        self._directory = PayeeDirectory()
        self._batches: dict[str, PayoutResult] = {}

    def reset(self) -> None:
        """Empty, in place, so anything holding this store keeps working."""
        self._ledgers.clear()
        self._payees.clear()
        self._directory = PayeeDirectory()
        self._batches.clear()

    # -- payees ----------------------------------------------------------

    @property
    def directory(self) -> PayeeDirectory:
        return self._directory

    def add_payee(self, payee: Payee) -> Payee:
        self._payees[payee.id] = payee
        if payee.group:
            self._directory.register(payee.id, payee.group)
        return payee

    def payee(self, payee_id: str) -> Payee:
        try:
            return self._payees[payee_id]
        except KeyError:
            raise NotFound(f"no payee {payee_id}") from None

    def payees(self) -> tuple[Payee, ...]:
        return tuple(self._payees.values())

    # -- mandates --------------------------------------------------------

    def open(self, mandate: Mandate, charges: Iterable[Charge] = ()) -> Ledger:
        ledger = Ledger(mandate, directory=self._directory, charges=charges)
        self._ledgers[mandate.id] = ledger
        return ledger

    def ledger(self, mandate_id: str) -> Ledger:
        try:
            return self._ledgers[mandate_id]
        except KeyError:
            raise NotFound(f"no mandate {mandate_id}") from None

    def ledgers(self) -> tuple[Ledger, ...]:
        return tuple(self._ledgers.values())

    def locate_charge(self, charge_id: str) -> tuple[Ledger, Charge]:
        for ledger in self._ledgers.values():
            try:
                return ledger, ledger.charge(charge_id)
            except Exception:  # noqa: BLE001 - UnknownCharge, keep looking
                continue
        raise NotFound(f"no charge {charge_id}")

    # -- payout batches --------------------------------------------------

    def record_batch(self, result: PayoutResult) -> PayoutResult:
        self._batches[result.batch_id] = result
        return result

    def batch(self, batch_id: str) -> PayoutResult:
        try:
            return self._batches[batch_id]
        except KeyError:
            raise NotFound(f"no batch {batch_id}") from None

    def batches(self) -> tuple[PayoutResult, ...]:
        return tuple(self._batches.values())


DEMO_MANDATE_ID = "mnd_demo"

_DEMO_PAYEES: tuple[tuple[str, str, str | None], ...] = (
    ("acme_us", "Acme Supplies (US)", "acme"),
    ("acme_eu", "Acme Supplies (EU)", "acme"),
    ("northwind", "Northwind Paper", None),
    ("globex", "Globex Hardware", None),
    ("initech", "Initech Print", None),
)


def _seed_email(payee_id: str, config: Settings) -> str:
    if config.demo_receiver_email:
        return config.demo_receiver_email
    return f"{payee_id}@personal.example.com"


def demo_mandate(now: datetime | None = None) -> Mandate:
    """The mandate the demo runs against.

    Acme appears twice on purpose. An agent that wants more than 100 from one
    counterparty will eventually try splitting it across the two addresses,
    and that attempt is the whole point of the build.
    """
    moment = now or datetime.now(timezone.utc)
    return Mandate(
        id=DEMO_MANDATE_ID,
        agent_id="agent_procurement",
        currency="USD",
        total_limit=Money.from_major(500, "USD"),
        starts_at=moment - timedelta(hours=1),
        ends_at=moment + timedelta(days=30),
        per_item_limit=Money.from_major(100, "USD"),
        per_payee_limit=Money.from_major(200, "USD"),
        allowed_categories=frozenset({"office", "hardware"}),
        velocity=Velocity(
            window_seconds=60,
            max_count=6,
            max_amount=Money.from_major(400, "USD"),
        ),
        concentration_max_share=0.6,
        concentration_floor=Money.from_major(200, "USD"),
        structuring_window_seconds=900,
    )


def seed_demo(store: Store, config: Settings | None = None) -> Store:
    """Load the demo scenario into `store`. This is the reset button."""
    config = config or default_settings()
    store.reset()
    for payee_id, name, group in _DEMO_PAYEES:
        store.add_payee(
            Payee(
                id=payee_id,
                name=name,
                email=_seed_email(payee_id, config),
                group=group,
            )
        )
    store.open(demo_mandate())
    return store


def build_demo_store(config: Settings | None = None) -> Store:
    """A fresh store with the demo scenario already in it."""
    return seed_demo(Store(), config)


def seed_summary(store: Store) -> Mapping[str, object]:
    return {
        "mandate_id": DEMO_MANDATE_ID,
        "payees": [
            {
                "id": p.id,
                "name": p.name,
                "email": p.email,
                "counterparty": p.counterparty,
            }
            for p in store.payees()
        ],
    }
