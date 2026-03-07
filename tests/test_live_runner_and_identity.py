import json

from src.core.decision_engine import MarketInputs
from src.execution.live_runner import LiveRunner
from src.main import _extract_asset_identity
from src.storage.storage import Storage


class StubDecisionEngine:
    def evaluate(self, *args, **kwargs):
        return {
            "timestamp": "2025-01-01T00:00:00+00:00",
            "collection_slug": "cool",
            "action": "PLACE_BID",
            "rationale": "all_hard_gates_passed",
            "risk_flags": [],
            "bid_price": 0.01,
        }


class StubReconciler:
    class _Health:
        healthy = True

    def health(self):
        return self._Health()


class StubOrderManager:
    def __init__(self):
        self.called = False

    def build_offer_payload(self, *args, **kwargs):
        self.called = True
        return {"payload": "x"}

    def create_offer(self, payload):
        return {"status": "DRY_RUN", "payload": payload}


class StubClient:
    pass


def test_cycle_persists_final_blocked_decision_when_target_asset_identity_missing(monkeypatch, tmp_path) -> None:
    storage = Storage(str(tmp_path / "db.sqlite3"))
    order_manager = StubOrderManager()
    runner = LiveRunner(
        cfg={
            "repricing": {"material_change_pct": 0.01, "cooldown_sec": 60, "max_reprices_per_hour": 2},
            "wallet": {"address_env": "WALLET_ADDRESS", "min_native_balance_eth": 0.01},
            "collections": {"allowlist": ["cool"]},
            "opensea": {"chain": "ethereum"},
        },
        client=StubClient(),
        decision_engine=StubDecisionEngine(),
        order_manager=order_manager,
        storage=storage,
        reconciler=StubReconciler(),
    )

    monkeypatch.setattr(runner, "reconcile_account_state", lambda: None)
    monkeypatch.setattr(runner, "check_wallet_balance", lambda: True)

    market = MarketInputs(
        collection_slug="cool",
        verified=True,
        recent_sales=[1.0],
        floor_asks=[1.1],
        floor_bids=[1.0],
        short_drift=0.0,
        sales_velocity=0.5,
        liquidity_score=0.8,
        rank_in_ask_ladder=1,
        rank_in_book=1,
        local_depth=1,
        inventory_age_sec=120,
        target_collection_contract="0xabc",
        target_token_id=None,
    )

    decision = runner.cycle(market)

    row = storage.conn.execute("SELECT decision_json FROM decisions ORDER BY id DESC LIMIT 1").fetchone()
    persisted = json.loads(row["decision_json"])

    assert decision == persisted
    assert decision["action"] == "DO_NOTHING"
    assert decision["rationale"] == "blocked_missing_target_asset_identity"
    assert "missing_target_asset_identity" in decision["risk_flags"]
    assert order_manager.called is False



def test_extract_asset_identity_preserves_numeric_zero_token_id() -> None:
    contract, token_id = _extract_asset_identity(
        {
            "listings": [
                {
                    "contract": "0x00000000000000000000000000000000000000cc",
                    "token_id": 0,
                }
            ]
        }
    )

    assert contract == "0x00000000000000000000000000000000000000cc"
    assert token_id == "0"


def test_extract_asset_identity_ignores_placeholder_identifier_values() -> None:
    contract, token_id = _extract_asset_identity(
        {
            "listings": [
                {
                    "contract": "0x00000000000000000000000000000000000000cc",
                    "token_id": None,
                    "identifier": {},
                    "asset": {"token_id": []},
                },
                {
                    "contract": "0x00000000000000000000000000000000000000dd",
                    "token_id": False,
                    "identifier": "   ",
                    "asset": {"token_id": {}},
                },
            ]
        }
    )

    assert contract is None
    assert token_id is None


def test_extract_asset_identity_accepts_numeric_zero_token_id() -> None:
    contract, token_id = _extract_asset_identity(
        {
            "listings": [
                {
                    "contract": "0x00000000000000000000000000000000000000cc",
                    "token_id": "",
                    "identifier": 0,
                }
            ]
        }
    )

    assert contract == "0x00000000000000000000000000000000000000cc"
    assert token_id == "0"
