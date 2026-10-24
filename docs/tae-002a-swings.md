# TAE-002A: causal confirmed swings

Research-only swing detection is implemented in `technical_engine.structure`.

A candidate at observation index `i` is confirmed only once `right` subsequent
observations have arrived. The pivot session and confirmation session are
separate. A swing high must strictly exceed all `left` preceding highs and
`right` succeeding highs; a swing low must strictly undercut corresponding
lows. Ties and flat extrema do not confirm. A nonnegative `tolerance_bps`
requires an additional price-relative margin. Input ordering uses validated
observation positions, not calendar days.

`ConfirmedSwing.usable_at` conservatively takes the latest `available_at`
and `retrieved_at` across the required prefix through the confirmation bar.
This makes backfilled historical records distinguishable from information
genuinely available at the time. The model does not claim a trade signal was
issued on the historical pivot date.

The implementation is deterministic and descriptive. It has no signal scoring,
ML training, brokerage access, strategy orders, or modifications to the
`Systematic-Trading-Research-Platform` orchestrator. No outputs are inserted
into existing frozen TAE-001 artifact schemas. A future separately versioned
artifact contract and thinkScript parity implementation require their own
validation gates.

## Acceptance tests

`uv run --locked pytest -q tests/test_structure.py`

Tests check strict extrema, tie policy, optional tolerance, delayed
confirmation, prefix invariance, short-history behavior, rejection of invalid
OHLCV, timestamp provenance, immutability and reproducibility.

A historical chart may place a marker at the pivot bar for visualization, but
must not display it as information actionable before confirmation and retrieval.
