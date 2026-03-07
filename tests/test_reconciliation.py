from src.core.reconciliation import Reconciler
from src.storage.storage import Storage


def _storage(tmp_path):
    return Storage(str(tmp_path / "agent.sqlite3"))


def test_health_unhealthy_before_reconciliation(tmp_path) -> None:
    reconciler = Reconciler(_storage(tmp_path))

    status = reconciler.health()

    assert status.healthy is False
    assert "missing_open_order_source" in status.reasons


def test_health_healthy_when_reconciled_and_in_sync(tmp_path) -> None:
    reconciler = Reconciler(_storage(tmp_path))

    reconciler.order_status_reconciliation([
        {"order_hash": "0x1", "status": "OPEN", "side": "offer"},
        {"order_hash": "0x2", "status": "FILLED", "side": "offer"},
    ])
    reconciler.listing_reconciliation([
        {"order_hash": "0xL1", "status": "OPEN"},
    ])
    reconciler.inventory_reconciliation([
        {"token_key": "collection:1", "collection": "collection", "token_id": "1"},
    ])
    reconciler.fills_reconciliation([])

    status = reconciler.health()

    assert status.healthy is True
    assert status.open_orders == 1
    assert status.open_bids == 1
    assert status.open_listings == 1
    assert status.inventory_count == 1


def test_health_unhealthy_when_order_state_mismatch(tmp_path) -> None:
    storage = _storage(tmp_path)
    reconciler = Reconciler(storage)

    reconciler.order_status_reconciliation([
        {"order_hash": "0x1", "status": "OPEN", "side": "offer"},
    ])
    reconciler.listing_reconciliation([])
    reconciler.inventory_reconciliation([])
    reconciler.fills_reconciliation([])
    storage.upsert_order("0x2", "OPEN", {"order_hash": "0x2", "status": "OPEN"}, side="offer")

    status = reconciler.health()

    assert status.healthy is False
    assert "open_order_mismatch" in status.reasons


def test_missing_state_source_is_unhealthy(tmp_path) -> None:
    reconciler = Reconciler(_storage(tmp_path))
    reconciler.mark_missing_source("missing_wallet_address")
    status = reconciler.health()
    assert status.healthy is False
    assert "missing_wallet_address" in status.reasons
