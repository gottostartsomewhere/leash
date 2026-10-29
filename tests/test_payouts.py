from __future__ import annotations

import json

import httpx
import pytest

from leash.config import Settings
from leash.money import Money
from leash.payouts import (
    PayoutError,
    PayoutItem,
    PayPalGateway,
    SimulatedGateway,
    build_gateway,
)

BASE = "https://api-m.sandbox.paypal.com"


def an_item(amount="80.00", receiver="payee@personal.example.com", charge_id="chg_1"):
    return PayoutItem(
        charge_id=charge_id,
        receiver=receiver,
        amount=Money.from_major(amount, "USD"),
        note="office supplies",
    )


def configured() -> Settings:
    return Settings(
        paypal_client_id="client-id",
        paypal_secret="client-secret",
        paypal_base_url=BASE,
    )


class Recorder:
    """A stand-in PayPal that records what it was sent."""

    def __init__(self, *, token_status=200, payout_status=201, batch_status="PENDING"):
        self.requests: list[httpx.Request] = []
        self.token_calls = 0
        self._token_status = token_status
        self._payout_status = payout_status
        self._batch_status = batch_status

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path

        if path == "/v1/oauth2/token":
            self.token_calls += 1
            if self._token_status != 200:
                return httpx.Response(self._token_status, json={"error": "nope"})
            return httpx.Response(
                200, json={"access_token": "tok_abc", "expires_in": 32400}
            )

        if path == "/v1/payments/payouts" and request.method == "POST":
            if self._payout_status not in (200, 201):
                return httpx.Response(self._payout_status, text="rejected")
            return httpx.Response(
                self._payout_status,
                json={
                    "batch_header": {
                        "payout_batch_id": "BATCH123",
                        "batch_status": self._batch_status,
                    }
                },
            )

        if path.startswith("/v1/payments/payouts/"):
            return httpx.Response(
                200,
                json={
                    "batch_header": {
                        "payout_batch_id": path.rsplit("/", 1)[-1],
                        "batch_status": "SUCCESS",
                    },
                    "items": [
                        {
                            "payout_item_id": "ITEM1",
                            "transaction_status": "SUCCESS",
                            "payout_item": {"sender_item_id": "chg_1"},
                        }
                    ],
                },
            )

        return httpx.Response(404, json={"error": "unexpected path"})


def gateway_for(recorder: Recorder) -> PayPalGateway:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(recorder.handle), base_url=BASE
    )
    return PayPalGateway(configured(), client=client)


# -- gateway selection ----------------------------------------------------


def test_without_credentials_the_simulated_gateway_is_used():
    assert build_gateway(Settings()).name == "simulated"


def test_with_credentials_the_real_gateway_is_used():
    assert build_gateway(configured()).name == "paypal"


def test_the_real_gateway_refuses_to_exist_without_credentials():
    with pytest.raises(PayoutError, match="credentials"):
        PayPalGateway(Settings())


# -- the simulated gateway ------------------------------------------------


async def test_the_simulated_gateway_settles_everything_by_default():
    result = await SimulatedGateway().send([an_item()], batch_id="b1")

    assert result.status == "SUCCESS"
    assert result.settled
    assert result.items[0].charge_id == "chg_1"


async def test_the_simulated_gateway_can_fail_a_named_receiver():
    gateway = SimulatedGateway(fail_receivers=["bad@personal.example.com"])

    result = await gateway.send(
        [an_item(receiver="bad@personal.example.com")], batch_id="b1"
    )

    assert result.status == "PARTIAL"
    assert not result.settled


async def test_an_unknown_simulated_batch_is_an_error():
    with pytest.raises(PayoutError):
        await SimulatedGateway().status("b_nope")


# -- the PayPal adapter ---------------------------------------------------


async def test_a_batch_is_sent_in_the_shape_paypal_expects():
    recorder = Recorder()
    gateway = gateway_for(recorder)

    result = await gateway.send([an_item()], batch_id="leash_abc")

    payout = next(r for r in recorder.requests if r.url.path == "/v1/payments/payouts")
    body = json.loads(payout.content)
    assert body["sender_batch_header"]["sender_batch_id"] == "leash_abc"
    assert body["items"][0] == {
        "recipient_type": "EMAIL",
        "receiver": "payee@personal.example.com",
        "amount": {"value": "80.00", "currency": "USD"},
        "note": "office supplies",
        "sender_item_id": "chg_1",
    }
    assert result.batch_id == "BATCH123"
    assert result.status == "PENDING"
    await gateway.aclose()


async def test_the_bearer_token_is_cached_across_batches():
    recorder = Recorder()
    gateway = gateway_for(recorder)

    await gateway.send([an_item()], batch_id="b1")
    await gateway.send([an_item()], batch_id="b2")

    assert recorder.token_calls == 1
    await gateway.aclose()


async def test_a_token_failure_surfaces_as_a_payout_error():
    gateway = gateway_for(Recorder(token_status=401))

    with pytest.raises(PayoutError, match="token request failed"):
        await gateway.send([an_item()], batch_id="b1")
    await gateway.aclose()


async def test_a_rejected_batch_surfaces_as_a_payout_error():
    gateway = gateway_for(Recorder(payout_status=400))

    with pytest.raises(PayoutError, match="rejected"):
        await gateway.send([an_item()], batch_id="b1")
    await gateway.aclose()


async def test_an_empty_batch_never_reaches_the_network():
    recorder = Recorder()
    gateway = gateway_for(recorder)

    with pytest.raises(PayoutError, match="at least one item"):
        await gateway.send([], batch_id="b1")

    assert recorder.requests == []
    await gateway.aclose()


async def test_per_item_status_is_read_back_off_a_batch():
    gateway = gateway_for(Recorder())

    result = await gateway.status("BATCH123")

    assert result.settled
    assert result.items[0].charge_id == "chg_1"
    assert result.items[0].payout_item_id == "ITEM1"
    await gateway.aclose()


async def test_a_response_without_a_batch_header_is_an_error():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 100})
        return httpx.Response(201, json={"nothing": "useful"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=BASE)
    gateway = PayPalGateway(configured(), client=client)

    with pytest.raises(PayoutError, match="batch_header"):
        await gateway.send([an_item()], batch_id="b1")
    await gateway.aclose()
