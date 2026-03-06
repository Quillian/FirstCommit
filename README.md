# OpenClaw Tiny-Live v1 (OpenSea Spread Capture)

Conservative execution agent with deterministic state machine, strict hard gates, and SQLite persistence.

## Safety profile
- Tiny-live inventory cap (default 1 NFT).
- Hard gate: `expected_net_pnl >= 0` enforced in code.
- Hard gate: verified collections, liquidity score, regime, balance, reconciliation health.
- Dry-run enabled by default for live mode safety.
- Repricing anti-churn controls (material threshold, cooldown, max/hour).

## State machine
`SCAN -> QUALIFY_COLLECTION -> QUOTE_BID -> WAIT_BID -> FILLED_LONG_NFT -> LIST_FOR_EXIT -> MONITOR_EXIT -> CANCEL_OR_REPRICE -> PAUSE_RISK`

## OpenSea capability path coverage
- Collection details/stats/events/listings/offers reads.
- Create offer/listing and cancel order write paths.
- Fulfillment data endpoints for listings/offers.
- Stream integration placeholder path for future event-driven layer.

## Install
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run
Paper mode:
```bash
python -m src.main --config config/agent.yaml
```

Live mode (safe test with writes disabled by default dry-run):
```bash
# keep mode=live and dry_run=true in config/agent.yaml
python -m src.main --config config/agent.yaml
```

## Environment variables
See `.env.example`.

Required minimum:
- `OPENSEA_API_KEY`
- `WALLET_ADDRESS`
- `PRIVATE_KEY` (for real signatures)
- `DB_PATH`

## Tests
```bash
pytest -q
```
