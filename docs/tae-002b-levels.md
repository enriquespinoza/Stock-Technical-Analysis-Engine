# TAE-002B: descriptive support and resistance

This module derives support levels from confirmed LOW swings and resistance
levels from confirmed HIGH swings. It is research only.

## Causal contract

- Swing pivots do not become eligible until their TAE-002A confirmation event.
- Only same-kind swings can join one cluster.
- Cluster distance is measured in basis points relative to the original
  anchor price, which never moves. Nearest eligible anchor wins; ties favor the
  earliest created level.
- Every confirmation appends a frozen `LevelEvent` snapshot; historical
  cluster states are never overwritten.
- Each event records pivot and confirmation indices/sessions, component
  swing count, observed price range, mean price, snapshot ID and conservative
  source availability/retrieval timestamps.
- `latest_levels` returns the latest state for each level within the passed
  ledger only. It does **not** assert that a level is still respected, active,
  predictive or tradeable.
- Cross-snapshot identities are not guaranteed. The event ledger must be
  reconstructed from each frozen, versioned OHLCV snapshot.
- A modern historical data backfill can have a recent `usable_at`; such
  observations must not be presented as live historical opportunities.

## Research boundaries

This milestone adds no trade orders, entry signals, execution permissions,
machine-learning weights, backtests or modifications to other repositories.
The existing TAE-001 artifact schema stays unchanged. Artifact publication
and any thinkScript equivalence are separate future acceptance gates.

## Validation

Run `uv run --locked pytest -q tests/test_levels.py` and full cross-platform
CI. Confirm deterministic clustering, no support/resistance cross-contamination,
no lookahead/prefix-invariance, no in-place rewriting, timestamp preservation,
short history behavior and strict parameter validation.
