# OPENCLAW HANDOFF

## Delivered
- Deterministic state machine with required states.
- Hard risk gates including non-negative expected net PnL gate.
- Weighted fair-value model (sales + ask depth + bid depth + drift + velocity).
- Expected exit model using sales cluster + ladder + rank + regime + drift + fill decay.
- Fill model with probability and expected time-to-fill.
- Repricing anti-churn guard.
- SQLite persistence for snapshots/history/orders/inventory/decisions/pnl/hourly/errors/reconciliation.
- Live execution path with signer integration, order payload builder, create offer/listing/cancel.
- Reconciliation hooks for orders and inventory.
- Polling-first design with stream integration path placeholder.
- Structured JSON decision output each cycle.

## Run Commands
1. `python -m venv .venv`
2. `source .venv/bin/activate`
3. `pip install -r requirements.txt`
4. `cp .env.example .env` and fill values
5. `python -m src.main --config config/agent.yaml`
6. `pytest -q`

## Live dry-run checklist
- set `mode: live`
- keep `dry_run: true`
- keep `write_enabled: false`

## Remaining manual steps before real writes
1. Wire real wallet balance via RPC in `LiveRunner.check_wallet_balance`.
2. Confirm exact OpenSea endpoint payload shapes for your account + chain.
3. Add nonce/chain-specific signing details required by current Seaport schema.
4. Enable stream consumer and map fill/listing events into reconciliation loop.
5. Flip `dry_run=false` and `write_enabled=true` only after sandbox validation.
