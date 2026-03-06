from typing import Any

import pytest

from src.client.opensea_client import OpenSeaClient
from src.execution.order_manager import ExecutionConfig, OrderManager
from src.execution.signer import Signer
from src.storage.storage import Storage


class DummyAuth:
    def headers(self) -> dict[str, str]:
        return {}


class DummyLimiter:
    def wait(self) -> None:
        return None


class CapturingClient(OpenSeaClient):
    def __init__(self) -> None:
        super().__init__("https://example.com/api/v2", DummyAuth(), DummyLimiter())
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def _request(self, method: str, path: str, payload=None, query=None):
        self.calls.append((method, path, payload))
        return {"ok": True, "order_hash": "0x1", "status": "OPEN"}


def test_endpoint_paths_constructed_from_chain_protocol(tmp_path) -> None:
    client = CapturingClient()
    storage = Storage(str(tmp_path / "db.sqlite3"))
    manager = OrderManager(
        client,
        Signer(None),
        storage,
        ExecutionConfig(mode="paper", dry_run=True, write_enabled=False, chain="ethereum", protocol="seaport"),
    )

    offer_payload = manager.build_offer_payload("cool", 0.01, "0xabc")
    manager.create_offer(offer_payload)
    listing_payload = manager.build_listing_payload("1", "cool", 0.02, "0xabc")
    manager.create_listing(listing_payload)
    manager.cancel_order("0xhash")
    client.fulfill_listing({"listing": {}})
    client.fulfill_offer({"offer": {}})

    # paper mode only calls fulfillment endpoints directly from client
    assert ("POST", "/listings/fulfillment_data", {"listing": {}}) in client.calls
    assert ("POST", "/offers/fulfillment_data", {"offer": {}}) in client.calls


def test_live_create_paths(tmp_path) -> None:
    client = CapturingClient()
    storage = Storage(str(tmp_path / "db.sqlite3"))
    manager = OrderManager(
        client,
        Signer("0xabc"),
        storage,
        ExecutionConfig(mode="live", dry_run=False, write_enabled=True, chain="ethereum", protocol="seaport"),
    )

    # bypass signer implementation to isolate path test
    manager._attach_signature = lambda payload: {**payload, "signature": "0xsig"}  # type: ignore
    manager.create_offer(manager.build_offer_payload("cool", 0.01, "0xabc"))
    manager.create_listing(manager.build_listing_payload("1", "cool", 0.02, "0xabc"))
    manager.cancel_order("0xhash")

    assert any(m == "POST" and p == "/orders/ethereum/seaport/offers" for (m, p, _) in client.calls)
    assert any(m == "POST" and p == "/orders/ethereum/seaport/listings" for (m, p, _) in client.calls)
    assert ("POST", "/orders/ethereum/seaport/0xhash/cancel", None) in client.calls


def test_invalid_order_payload_prevented() -> None:
    signer = Signer(None)
    with pytest.raises(ValueError):
        signer.sign_order_payload({"foo": "bar"})
