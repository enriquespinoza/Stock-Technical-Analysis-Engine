# TAE-003: retrospective chronological forward-return evaluation

This first evaluation stage is **research only**. It does not issue signals,
select a profitable strategy, place trades, or establish prospective validity.

## Inputs and time axes

`forward_evaluation.evaluate_forward_returns` uses the validated OHLCV
snapshot and deterministic TAE-002D event ledger. It validates supplied
external event tuples against a recomputed ledger for the same snapshot and
configuration. Each setup is known no earlier than its own recorded
`usable_at`; source retrieval may occur long after the historical session.

The user fixes one `cutoff_session`, ordered positive observation-bar
`horizons` (defaults 1, 5, 10) and an optional `embargo_bars` immediately
after the cutoff. The cutoff is inside the observed history, strictly before
its final session. All event definitions and settings must be selected
without consulting holdout returns. This API does not automatically enforce
such a research governance policy.

## Forward labels

For an event on observation index `i`, horizon `h` is the close-to-close
simple return `close[i+h] / close[i] - 1`. `directional_return` negates
this value for DOWN events, for descriptive comparability only. This is
**not** an executable strategy return: the event is detected at close `i`,
which is not guaranteed to be a fillable entry. Transaction costs, slippage,
risk, position sizing, survivorship bias and corporate-action policy must
be separately handled for a trading evaluation.

Development events are those on or before the cutoff. Development labels
with a target ending after the cutoff are **CENSORED**, preventing use of
holdout future outcomes for development analysis. Events in the post-cutoff
embargo are excluded. Holdout events start beyond the embargo. Events whose
horizon extends beyond the final bar are **CENSORED** rather than assigned
zero or silently treated as an observed return. A censored label has no
end-close, target date or numerical return.

Every label records event identity, breakout ID, kind, direction, source
snapshot, event `usable_at`, observation index/session, partition, horizon,
maturity, endpoint and raw/directional returns. Immutable summary rows
include matured and censored counts, arithmetic means and fraction of
positive directional returns (undefined when no matured labels).

## Interpretation and boundaries

**Chronological holdout is not prospective out-of-sample validation.** A
single modern historical backfill may make all setup timestamps retrospectively
retrievable; this module therefore marks its method as
`retrospective_chronological_holdout_not_prospective`. True historical
point-in-time availability requires independent archived vintages or a
prospectively collected data stream.

Repeated events on the same symbol, overlapping return windows, and shared
breakout IDs are dependent observations. This first milestone deliberately
does not report t-tests, confidence intervals, multiple-hypothesis-adjusted
p-values, cross-sectional benchmarks or claims of predictive value.
Before interpreting findings, future work must independently audit universe
selection, benchmark definition, pre-registration, sampling variation and
realistic observations after the close. This module is a pure in-memory
evaluation and does not alter frozen TAE-001 or TAE-002E manifests.

## Acceptance

Cross-platform `uv run --locked pytest -rs -q`, `uv run --locked ruff check .`,
`uv run --locked ruff format --check .` and `uv build`. Review deterministic
returns, direction signs, horizon endpoints, cutoff purging, embargo,
right-censoring, empty summaries, immutable provenance, data/config validation
and refusal of mismatched event streams.
