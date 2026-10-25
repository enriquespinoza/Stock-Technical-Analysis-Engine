# TAE-002C: causal descriptive trend classification

Implementation: `src/technical_engine/trends.py`. This is a research-only
event ledger, not a predictor or trading strategy.

## Causal input and event order

- Use only TAE-002A `confirmed_swings` based on validated, point-in-time
  OHLCV. A swing is observed only at its **confirmation index**, never at its
  earlier pivot index.
- Each confirmed swing appends one frozen `TrendEvent`, even when the
  classification remains unchanged. The prior ledger is never rewritten.
- `TrendEvent` records pivot and confirmation sessions and indices, swing
  kind and price, latest observed high/low pivot information, the most recent
  structural comparisons, snapshot ID, and conservative knowledge timestamps.
- `usable_at` includes source availability and retrieval knowledge time
  inherited from the confirmed swing. A historical backfill retrieved later
  must not be represented as an actual historical signal.
- Events reflect the most recently **confirmed** pivots; a more recent
  unconfirmed pivot is not used for classification.
- Config is explicit: `TrendConfig(swing=SwingConfig(...),
  comparison_tolerance_bps=...)`. Tolerances use the preceding comparable
  pivot price; a nonnegative basis-point band treats near-equal prices as equal.

## Structural comparisons

The classifier compares only successive confirmed swings of the same kind.

| High comparison | Rule |
| --- | --- |
| `HH` | Current confirmed HIGH exceeds prior confirmed HIGH by more than tolerance |
| `LH` | Current confirmed HIGH is below prior confirmed HIGH by more than tolerance |
| `EH` | Confirmed HIGHs are equal within tolerance |

| Low comparison | Rule |
| --- | --- |
| `HL` | Current confirmed LOW exceeds prior confirmed LOW by more than tolerance |
| `LL` | Current confirmed LOW is below prior confirmed LOW by more than tolerance |
| `EL` | Confirmed LOWs are equal within tolerance |

Trend states:

| State | Rule |
| --- | --- |
| `INDETERMINATE` | Fewer than two confirmed HIGHs or fewer than two confirmed LOWs |
| `UPTREND` | Latest comparisons are `HH` and `HL` |
| `DOWNTREND` | Latest comparisons are `LH` and `LL` |
| `SIDEWAYS` | Both comparisons exist but are mixed or equal |

These labels describe confirmed swing structure. `SIDEWAYS` is deliberately a
conservative *catch-all for conflicting/equal structure*, not proof of
low volatility or a bounded trading range. An apparent reversal progresses
through updated events; existing events are not backdated or altered.
`latest_trend(events)` reads only the final event in the supplied as-of
ledger and is not an assertion of an actionable current signal.

## Research boundaries

- No use of future bars relative to each recorded confirmation event.
- No brokerage credentials, portfolio permissions, order placement,
  entry/exit rules, returns forecast, or profitability claims.
- Existing TAE-001 artifact schemas and TAE-002A/002B implementations
  remain unchanged. Versioned trend artifact exports and integration into
  the top-level research orchestrator are separate acceptance gates.
- Each dataset snapshot has its own trend ledger. No stable
  cross-snapshot event identifier or live-trading guarantee is claimed.
- No claimed thinkorswim signal parity. Independent thinkScript translation
  and historical/forward evaluations are separate milestones.

## Acceptance

Run:

```bash
uv run --locked pytest -rs -q
uv run --locked ruff check .
uv run --locked ruff format --check .
uv build
```

Validate on Windows and Linux CI, including deterministic replay, short
history, strict argument validation, higher/lower/equal pivots, mixed
structures, reversals, prefix invariance, delayed confirmation,
knowledge timestamps and frozen events.

Software correctness does not establish predictive effectiveness.
