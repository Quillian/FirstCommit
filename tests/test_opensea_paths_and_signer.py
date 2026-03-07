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
        self.calls: list[tuple[str, str, dict[str, Any] | None, dict[str, Any] | None]] = []

    def _request(self, method: str, path: str, payload=None, query=None):
        self.calls.append((method, path, payload, query))
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

    offer_payload = manager.build_offer_payload("cool", 0.01, "0x0000000000000000000000000000000000000001", "0x0000000000000000000000000000000000000011", "0x0000000000000000000000000000000000000012")
    manager.create_offer(offer_payload)
    listing_payload = manager.build_listing_payload("1", "cool", 0.02, "0x0000000000000000000000000000000000000001", "0x0000000000000000000000000000000000000011", "0x0000000000000000000000000000000000000012")
    manager.create_listing(listing_payload)
    manager.cancel_order("0xhash")
    client.fulfill_listing({"listing": {}}, chain="ethereum", protocol="seaport")
    client.fulfill_offer({"offer": {}}, chain="ethereum", protocol="seaport")
    client.get_events_by_collection("cool")

    assert any(m == "POST" and p == "/orders/ethereum/seaport/listings/fulfillment_data" for (m, p, _, _) in client.calls)
    assert any(m == "POST" and p == "/orders/ethereum/seaport/offers/fulfillment_data" for (m, p, _, _) in client.calls)
    assert any(m == "GET" and p == "/events/collection" and q == {"collection_slug": "cool"} for (m, p, _, q) in client.calls)


def test_live_create_paths(tmp_path) -> None:
    client = CapturingClient()
    storage = Storage(str(tmp_path / "db.sqlite3"))
    manager = OrderManager(
        client,
        Signer("0xabc"),
        storage,
        ExecutionConfig(mode="live", dry_run=False, write_enabled=True, chain="ethereum", protocol="seaport"),
    )

    manager._attach_signature = lambda payload: {**payload, "signature": "0xsig"}  # type: ignore
    manager.create_offer(manager.build_offer_payload("cool", 0.01, "0x0000000000000000000000000000000000000001", "0x0000000000000000000000000000000000000011", "0x0000000000000000000000000000000000000012"))
    manager.create_listing(manager.build_listing_payload("1", "cool", 0.02, "0x0000000000000000000000000000000000000001", "0x0000000000000000000000000000000000000011", "0x0000000000000000000000000000000000000012"))
    manager.cancel_order("0xhash")

    assert any(m == "POST" and p == "/orders/ethereum/seaport/offers" for (m, p, _, _) in client.calls)
    assert any(m == "POST" and p == "/orders/ethereum/seaport/listings" for (m, p, _, _) in client.calls)
    assert ("POST", "/orders/ethereum/seaport/0xhash/cancel", {}, None) in client.calls


def test_invalid_order_payload_prevented() -> None:
    signer = Signer(None)
    with pytest.raises(ValueError):
        signer.sign_order_payload({"foo": "bar"})


def test_order_payload_is_seaport_components(tmp_path) -> None:
    client = CapturingClient()
    storage = Storage(str(tmp_path / "db.sqlite3"))
    manager = OrderManager(
        client,
        Signer(None),
        storage,
        ExecutionConfig(mode="paper", dry_run=True, write_enabled=False, chain="ethereum", protocol="seaport"),
    )

    payload = manager.build_offer_payload("cool", 0.01, "0x0000000000000000000000000000000000000001", "0x0000000000000000000000000000000000000011", "0x0000000000000000000000000000000000000012")
    params = payload["protocol_data"]["parameters"]
    assert "offer" in params and "consideration" in params
    assert params["offer"][0]["startAmount"].isdigit()
    assert "eip712" not in payload



def test_signer_typed_data_excludes_eip712domain() -> None:
    payload = {
        "chain": "ethereum",
        "protocol": "seaport",
        "protocol_data": {
            "parameters": {
                "offerer": "0x0000000000000000000000000000000000000001",
                "zone": "0x0000000000000000000000000000000000000000",
                "offer": [{"itemType": 1, "token": "0x0000000000000000000000000000000000000012", "identifierOrCriteria": "0", "startAmount": "1", "endAmount": "1"}],
                "consideration": [{"itemType": 2, "token": "0x0000000000000000000000000000000000000011", "identifierOrCriteria": "1", "startAmount": "1", "endAmount": "1", "recipient": "0x0000000000000000000000000000000000000001"}],
                "orderType": 0,
                "startTime": "1",
                "endTime": "2",
                "zoneHash": "0x" + "00" * 32,
                "salt": "3",
                "conduitKey": "0x" + "00" * 32,
                "counter": "0",
            }
        },
    }

    _, message_types, _ = Signer._seaport_typed_data(payload)
    assert "EIP712Domain" not in message_types
    assert "OrderComponents" in message_types

def test_order_payload_requires_non_zero_tokens(tmp_path) -> None:
    client = CapturingClient()
    storage = Storage(str(tmp_path / "db.sqlite3"))
    manager = OrderManager(
        client,
        Signer(None),
        storage,
        ExecutionConfig(mode="paper", dry_run=True, write_enabled=False, chain="ethereum", protocol="seaport"),
    )

    with pytest.raises(ValueError, match="invalid_order_payload_collection_contract"):
        manager.build_offer_payload(
            "cool",
            0.01,
            "0x0000000000000000000000000000000000000001",
            "0x0000000000000000000000000000000000000000",
            "0x0000000000000000000000000000000000000012",
        )

    with pytest.raises(ValueError, match="invalid_order_payload_payment_token"):
        manager.build_offer_payload(
            "cool",
            0.01,
            "0x0000000000000000000000000000000000000001",
            "0x0000000000000000000000000000000000000011",
            "0x0000000000000000000000000000000000000000",
        )
