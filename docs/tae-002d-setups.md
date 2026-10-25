# TAE-002D: causal breakout and retest research

Implementation: `technical_engine.setups`. This milestone describes observable
price/level interactions; it does **not** issue orders, predict returns,
define a profitable trading strategy, or change orchestrator authority.

## Inputs and knowledge gate

- Use immutable, snapshot-scoped TAE-002B `LevelEvent` ledgers, which derive
  from TAE-002A confirmed swings. Confirmations on observation `k` first
  become eligible for a breakout on **k+1**. Prior values cannot be backdated.
- TAE-002C contributes a descriptive `trend_context` from confirmations
  *strictly before* the breakout or follow-up bar. Context does not filter
  events and does not replace the independently validated levels.
- The detected breakout freezes the original cluster's `anchor_price`,
  confirming observation and level identity. Later cluster updates must
  not retroactively modify prior setup events.
- Every `SetupEvent` is immutable and carries the snapshot, event index,
  breakout ID, event kind, direction, original level, observation index and
  session, breakout index and session, close, trend context, and conservative
  source availability/retrieval knowledge times.
- Historical `usable_at` is at least the observation's input knowledge
  time; backfills are not mislabeled as live signals.

## Deterministic rules

- **Upside breakout:** a close crosses strictly above a previously confirmed
  resistance *anchor* plus `breakout_buffer_bps`. The preceding close must
  be at or below the threshold.
- **Downside breakout:** symmetric close-crossing of a previously confirmed
  support anchor minus the buffer. Intrabar wicks alone never suffice.
- **Retest:** only on subsequent observations, within `max_followup_bars`,
  after an upside breakout a bar's low approaches the frozen anchor within
  `retest_tolerance_bps` while its close remains at/above the anchor.
  A downside retest requires its high to approach the anchor while its close
  remains at/below the anchor. At most one retest per breakout.
- **Failed breakout:** before the follow-up window closes, an upside
  breakout subsequently closes strictly *below* the frozen resistance
  anchor; a downside breakout subsequently closes strictly *above*
  the frozen support anchor. Failures take precedence over retests on the
  same bar. A failure closes the sequence.
- The follow-up window counts observation bars, not calendar days.
  An unfinished breakout expires without a fabricated expiry event.
- At most one active setup per level ID. A fresh crossing may create another
  sequence after the prior sequence fails or expires, but failure bars
  cannot simultaneously create a new sequence for the same level.
- Ties and buffer boundaries are deliberately strict and deterministic.
- The close-of-bar event is research evidence, not evidence that execution
  could have occurred at that close.

## Limits and validation

This milestone does not score prediction quality, calculate forward returns,
post trade orders, revise the frozen TAE-001 artifact schema, integrate with
the top-level orchestrator, or assert thinkScript equivalence. A cluster
anchor may no longer be economically relevant; the event is a historical
price crossing and must not be read as a validated investment signal.

Acceptance covers deterministic synthetic ascending/descending breakouts,
retests/failures, confirmation delays, wick-only bars, tolerance boundaries,
expiry, prefix invariance, immutable events, source-knowledge timestamps,
malformed configurations and invalid market data.

Run `uv run --locked pytest -rs -q`, `uv run --locked ruff check .`,
`uv run --locked ruff format --check .` and `uv build`; confirm Windows
and Linux CI. Any predictive testing remains a separate research milestone.
