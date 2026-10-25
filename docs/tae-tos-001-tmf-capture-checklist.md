# TAE-TOS-001 live capture checklist — TMF confirmed swings

This is a **manual platform observation protocol**, not a completed parity
result. The candidate study at `thinkscript/TAE_Confirmed_Swings_Parity.ts`
was supplied by the operator and displayed HIGH/LOW bubbles in a screenshot.
Compilation/output equivalence and historical execution are not attested.

## Before collecting any signals

1. Keep PR #12 in draft. Record the exact saved study bytes and settings:
   `leftBars=2`, `rightBars=2`, `toleranceBps=0`.
2. Freeze an independent **daily OHLCV input_snapshot.json** of TMF, with
   session dates, adjustment policy, retrieval time and snapshot ID. The
   source must be a real captured dataset, not prices read back from expected
   Python signals. Keep its original source payload if available.
3. Check each chart date, open, high, low and close against the snapshot.
   **Stop** for missing bars, date offsets, revision/adjustment differences,
   differing bar histories or inconsistencies. A chart set to `1Y 1D` does
   not establish exact equivalence with the input snapshot.
4. Fix the **same zero-based session range** in both systems. Exclude warmup
   observations without adequate preceding bars. Do not infer a bar index
   from pixels or calendar-day subtraction.

## Observing events

The candidate thinkScript plots a pivot **on its confirmation bar**. In the
default 2/2 configuration, the pivot occurs two observed bars before its
confirmation. Read the displayed bubble date after removing thousands-style
commas: e.g. `20,260,625` represents `20260625`, or `2026-06-25`.
Read the price from the `ConfirmedHigh` / `ConfirmedLow` plot at the
**confirmation** bar; it is the pivot high/low, not the confirmation close.
Preserve chart screenshots, exact study source and operator notes.

Map both dates to the frozen input snapshot's zero-based bar indices. Write
one independently observed event per CSV row in this exact order:

```csv
kind,pivot_index,confirmation_index,pivot_session,confirmation_session,price
```

The header alone represents no recorded events; never populate this file
by copying Python's event ledger. Keep observations as captured even if they
disagree with Python.

## Comparing and interpreting

Run `compare_swing_capture` on the frozen `OHLCVDataset`, fixed
`SwingConfig(2,2,0)`, original study bytes, and independently observed CSV.
Record all missing, extra, session and price differences with case-by-case
resolution. Note that `ThinkScriptCapture` metadata is operator asserted:
`comparison_complete` only means the supplied records matched Python, and
`platform_execution_verified` remains false.

No accepted study exists until an independent reviewer confirms data
equivalence, evidence authenticity, event reconciliation and methodology.
TAE-TOS-002 OnDemand, TAE-TOS-003 paperMoney and ORCH integration are separate.
