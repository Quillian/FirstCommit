import json

from src.core.decision_engine import DecisionEngine, MarketInputs
from src.execution.order_manager import ExecutionConfig, OrderManager
from src.execution.signer import Signer
from src.storage.storage import Storage


class NoWriteClient:
    def __init__(self) -> None:
        self.calls = []

    def create_item_offer(self, chain, protocol, order):
        self.calls.append(("offer", chain, protocol, order))
        return {"status": "OPEN", "order_hash": "0xoffer"}


class TrackingSigner(Signer):
    def __init__(self) -> None:
        super().__init__(private_key=None)
        self.validated = False

    def _validate_order_payload(self, payload):
        self.validated = True
        return super()._validate_order_payload(payload)


def _cfg() -> dict:
    return {
        "size_controls": {"bid_size_eth": 0.01, "max_open_inventory": 1},
        "pricing": {"edge_buffer_pct": 0.02, "max_bid_price_eth": 0.05, "velocity_norm_denominator": 100},
        "fees": {"use_collection_fees": True, "default_marketplace_bps": 250, "default_royalties_bps": 500},
        "gas": {"per_trade_eth": 0.0008},
        "risk": {"staircase_drop_pct": 0.07},
        "throttling": {"scheduler_cycle_sec": 30},
    }


def test_dry_run_invokes_signer_validation_but_no_submit(tmp_path) -> None:
    storage = Storage(str(tmp_path / "db.sqlite3"))
    client = NoWriteClient()
    signer = TrackingSigner()
    manager = OrderManager(
        client,
        signer,
        storage,
        ExecutionConfig(mode="live", dry_run=True, write_enabled=True, chain="ethereum", protocol="seaport"),
    )
    payload = manager.build_offer_payload(
        "cool",
        "0x00000000000000000000000000000000000000cc",
        "1",
        0.01,
        "0x0000000000000000000000000000000000000001",
    )
    result = manager.create_offer(payload)

    assert result["status"] == "DRY_RUN"
    assert signer.validated is True
    assert client.calls == []


def test_storage_persists_orders_fills_inventory_and_status_history(tmp_path) -> None:
    storage = Storage(str(tmp_path / "db.sqlite3"))
    storage.upsert_order("0x1", "OPEN", {"collection": "cool", "collection_contract": "0xabc", "token_id": "1"}, side="offer")
    storage.record_fill("0x1", "0xabc:1", "offer", 0.01, "exchange", {"ok": True})
    storage.replace_inventory([{"token_key": "0xabc:1", "collection": "cool", "token_id": "1"}])
    storage.replace_inventory([])

    assert storage.count_open_orders() == 1
    assert storage.count_fills() == 1
    inv_closed = storage.conn.execute("SELECT status FROM inventory WHERE token_key='0xabc:1'").fetchone()["status"]
    hist = storage.conn.execute("SELECT COUNT(*) as c FROM order_status_history WHERE order_hash='0x1'").fetchone()["c"]
    assert inv_closed == "CLOSED"
    assert hist >= 1


def test_budget_cap_exceeded_path() -> None:
    engine = DecisionEngine(_cfg())
    inputs = MarketInputs(
        collection_slug="abc",
        verified=True,
        recent_sales=[0.05, 0.052, 0.051, 0.053, 0.054],
        floor_asks=[0.06, 0.061],
        floor_bids=[0.019, 0.018],
        short_drift=0.02,
        sales_velocity=0.8,
        liquidity_score=0.9,
        rank_in_ask_ladder=1,
        rank_in_book=1,
        local_depth=10,
        inventory_age_sec=0,
        marketplace_bps=0,
        royalties_bps=0,
    )
    decision = engine.evaluate(inputs, inventory_count=0, reconciliation_healthy=True, wallet_sufficient=True)
    assert "budget_cap_exceeded" in decision["risk_flags"]
    assert decision["budget_context"]["cap_gap_eth"] > 0


def test_decision_persistence_after_runtime_mutation(tmp_path) -> None:
    storage = Storage(str(tmp_path / "db.sqlite3"))
    decision = {"action": "DO_NOTHING", "risk_flags": ["missing_target_asset_identity"]}
    storage.log_decision("cool", decision)
    row = storage.conn.execute("SELECT decision_json FROM decisions ORDER BY id DESC LIMIT 1").fetchone()
    assert json.loads(row["decision_json"]) == decision
