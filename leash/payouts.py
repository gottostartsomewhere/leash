"""Moving the money, once the mandate has said yes.

Two gateways behind one protocol. `PayPalGateway` talks to the real Payouts
API; `SimulatedGateway` needs no credentials and is deterministic, so the
engine, the API and the red-team runs are all testable without a network.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Final, Iterable, Mapping, Protocol, Sequence

import httpx

from .config import Settings, settings as default_settings
from .money import Money


class PayoutError(RuntimeError):
    """The processor refused the batch, or never answered."""


@dataclass(frozen=True, slots=True)
class PayoutItem:
    """One row of a batch: who gets paid, how much, and for which charge."""

    charge_id: str
    receiver: str
    amount: Money
    note: str = ""

    def to_payload(self) -> dict[str, object]:
        return {
            "recipient_type": "EMAIL",
            "receiver": self.receiver,
            "amount": {
                "value": f"{self.amount.major}",
                "currency": self.amount.currency,
            },
            "note": self.note,
            "sender_item_id": self.charge_id,
        }


@dataclass(frozen=True, slots=True)
class PayoutItemResult:
    charge_id: str
    status: str
    payout_item_id: str | None = None


#: Item statuses where the money is with the recipient or still on its way to
#: them. UNCLAIMED is in here on purpose: the recipient has no PayPal account
#: yet, the money is held for them, and it only comes back if it expires.
HOLDS_MONEY: Final[frozenset[str]] = frozenset(
    {"SUCCESS", "PENDING", "PROCESSING", "UNCLAIMED", "ONHOLD"}
)

#: Item statuses where the money came back or never left. These are the ones
#: that can appear *after* we have already recorded a charge as settled, which
#: is the entire reason reconciliation exists.
CAME_BACK: Final[frozenset[str]] = frozenset(
    {"FAILED", "RETURNED", "REVERSED", "REFUNDED", "BLOCKED", "CANCELED", "DENIED"}
)


def holds_money(status: str) -> bool:
    """Did this item end up with the recipient, or is it still heading there?

    Anything unrecognised is treated as not holding money. A status we have
    never seen is not a reason to keep claiming a payment succeeded.
    """
    return status.strip().upper() in HOLDS_MONEY


@dataclass(frozen=True, slots=True)
class PayoutResult:
    """What the processor said about a batch."""

    batch_id: str
    status: str
    gateway: str
    items: tuple[PayoutItemResult, ...] = ()
    raw: Mapping[str, object] = field(default_factory=dict)

    @property
    def settled(self) -> bool:
        return self.status in {"SUCCESS", "COMPLETED"}

    def to_dict(self) -> dict[str, object]:
        return {
            "batch_id": self.batch_id,
            "status": self.status,
            "gateway": self.gateway,
            "settled": self.settled,
            "items": [
                {
                    "charge_id": i.charge_id,
                    "status": i.status,
                    "payout_item_id": i.payout_item_id,
                }
                for i in self.items
            ],
        }


class PayoutGateway(Protocol):
    name: str

    async def send(
        self, items: Sequence[PayoutItem], *, batch_id: str
    ) -> PayoutResult: ...

    async def status(self, batch_id: str) -> PayoutResult: ...


class SimulatedGateway:
    """A processor that always answers, instantly, the same way.

    Not a stub for the sake of tests. The red-team run makes thousands of
    authorizations, and none of them should depend on a sandbox being up.
    """

    name = "simulated"

    def __init__(self, *, fail_receivers: Iterable[str] = ()) -> None:
        self._fail = frozenset(fail_receivers)
        self._batches: dict[str, PayoutResult] = {}

    async def send(
        self, items: Sequence[PayoutItem], *, batch_id: str
    ) -> PayoutResult:
        results = tuple(
            PayoutItemResult(
                charge_id=item.charge_id,
                status="FAILED" if item.receiver in self._fail else "SUCCESS",
                payout_item_id=f"sim_{item.charge_id}",
            )
            for item in items
        )
        status = "SUCCESS" if all(r.status == "SUCCESS" for r in results) else "PARTIAL"
        result = PayoutResult(
            batch_id=batch_id,
            status=status,
            gateway=self.name,
            items=results,
            raw={"simulated": True},
        )
        self._batches[batch_id] = result
        return result

    async def status(self, batch_id: str) -> PayoutResult:
        try:
            return self._batches[batch_id]
        except KeyError:
            raise PayoutError(f"unknown batch {batch_id}") from None

    def set_item_status(self, batch_id: str, charge_id: str, status: str) -> None:
        """Change what this gateway says about an item after the fact.

        Real processors do this, which is the whole reason reconciliation
        exists: a payout accepted as PENDING can turn into RETURNED an hour
        later and nothing comes back to tell you. Without a way to reproduce
        that, the recovery path could only ever be tested by waiting for a
        genuine failure, and the demo could not show it at all.
        """
        batch = self._batches.get(batch_id)
        if batch is None:
            raise PayoutError(f"unknown batch {batch_id}")
        items = tuple(
            PayoutItemResult(
                charge_id=item.charge_id,
                status=status if item.charge_id == charge_id else item.status,
                payout_item_id=item.payout_item_id,
            )
            for item in batch.items
        )
        every = {item.status for item in items}
        self._batches[batch_id] = PayoutResult(
            batch_id=batch.batch_id,
            status="SUCCESS" if every == {"SUCCESS"} else "PARTIAL",
            gateway=batch.gateway,
            items=items,
            raw=batch.raw,
        )


class PayPalGateway:
    """PayPal Payouts v1, sandbox or live, decided by the base URL."""

    name = "paypal"

    def __init__(
        self,
        config: Settings | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._config = config or default_settings()
        if not self._config.paypal_configured:
            raise PayoutError(
                "PayPal credentials are not set; "
                "export LEASH_PAYPAL_CLIENT_ID and LEASH_PAYPAL_SECRET"
            )
        self._client = client
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._config.paypal_base_url,
                timeout=self._config.request_timeout_seconds,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _access_token(self) -> str:
        """Client-credentials token, cached until shortly before it expires."""
        if self._token and time.monotonic() < self._token_expires_at:
            return self._token

        http = await self._http()
        response = await http.post(
            "/v1/oauth2/token",
            auth=(self._config.paypal_client_id or "", self._config.paypal_secret or ""),
            data={"grant_type": "client_credentials"},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if response.status_code != 200:
            raise PayoutError(f"token request failed: {response.status_code}")

        payload = response.json()
        self._token = payload["access_token"]
        # Renew a minute early rather than discovering expiry mid-batch.
        self._token_expires_at = time.monotonic() + max(
            0, int(payload.get("expires_in", 300)) - 60
        )
        return self._token or ""

    async def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {await self._access_token()}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _parse(payload: Mapping[str, object], gateway: str) -> PayoutResult:
        header = payload.get("batch_header")
        if not isinstance(header, Mapping):
            raise PayoutError("payout response had no batch_header")
        batch_id = str(header.get("payout_batch_id") or "")
        if not batch_id:
            # Settling charges against a reply we cannot identify later would
            # leave the ledger claiming money moved with no way to check.
            raise PayoutError("payout response had no batch id")

        raw_items = payload.get("items") or []
        items: list[PayoutItemResult] = []
        if isinstance(raw_items, Sequence):
            for entry in raw_items:
                if not isinstance(entry, Mapping):
                    continue
                payout_item = entry.get("payout_item") or {}
                sender_item_id = (
                    payout_item.get("sender_item_id")
                    if isinstance(payout_item, Mapping)
                    else None
                )
                items.append(
                    PayoutItemResult(
                        charge_id=str(sender_item_id or ""),
                        status=str(entry.get("transaction_status", "UNKNOWN")),
                        payout_item_id=(
                            str(entry["payout_item_id"])
                            if "payout_item_id" in entry
                            else None
                        ),
                    )
                )

        return PayoutResult(
            batch_id=batch_id,
            status=str(header.get("batch_status", "UNKNOWN")),
            gateway=gateway,
            items=tuple(items),
            raw=payload,
        )

    async def send(
        self, items: Sequence[PayoutItem], *, batch_id: str
    ) -> PayoutResult:
        if not items:
            raise PayoutError("a payout batch needs at least one item")

        http = await self._http()
        response = await http.post(
            "/v1/payments/payouts",
            headers=await self._headers(),
            json={
                "sender_batch_header": {
                    "sender_batch_id": batch_id,
                    "email_subject": self._config.email_subject,
                    "email_message": self._config.email_message,
                },
                "items": [item.to_payload() for item in items],
            },
        )
        if response.status_code not in (200, 201):
            raise PayoutError(
                f"payout batch rejected ({response.status_code}): {response.text[:400]}"
            )
        return self._parse(response.json(), self.name)

    async def status(self, batch_id: str) -> PayoutResult:
        http = await self._http()
        response = await http.get(
            f"/v1/payments/payouts/{batch_id}", headers=await self._headers()
        )
        if response.status_code != 200:
            raise PayoutError(
                f"batch lookup failed ({response.status_code}): {response.text[:400]}"
            )
        return self._parse(response.json(), self.name)


def build_gateway(config: Settings | None = None) -> PayoutGateway:
    """The real gateway when credentials exist, the simulated one otherwise."""
    config = config or default_settings()
    if config.paypal_configured:
        return PayPalGateway(config)
    return SimulatedGateway()
