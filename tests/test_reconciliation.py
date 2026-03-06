from src.core.reconciliation import Reconciler
from src.storage.storage import Storage


def _storage(tmp_path):
    return Storage(str(tmp_path / "agent.sqlite3"))


def test_health_unhealthy_before_reconciliation(tmp_path) -> None:
    reconciler = Reconciler(_storage(tmp_path))

    status = reconciler.health()

    assert status.healthy is False


def test_health_healthy_when_reconciled_and_in_sync(tmp_path) -> None:
    reconciler = Reconciler(_storage(tmp_path))

    reconciler.order_status_reconciliation([
        {"order_hash": "0x1", "status": "OPEN"},
        {"order_hash": "0x2", "status": "FILLED"},
    ])
    reconciler.inventory_reconciliation([
        {"token_key": "collection:1", "collection": "collection", "token_id": "1"},
    ])

    status = reconciler.health()

    assert status.healthy is True
    assert status.open_orders == 1
    assert status.inventory_count == 1


def test_health_unhealthy_when_order_state_mismatch(tmp_path) -> None:
    storage = _storage(tmp_path)
    reconciler = Reconciler(storage)

    reconciler.order_status_reconciliation([
        {"order_hash": "0x1", "status": "OPEN"},
    ])
    storage.upsert_order("0x2", "OPEN", {"order_hash": "0x2", "status": "OPEN"})
    reconciler.inventory_reconciliation([])

    status = reconciler.health()

    assert status.healthy is False
