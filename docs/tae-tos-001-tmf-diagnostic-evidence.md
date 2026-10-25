# TAE-TOS-001 — TMF confirmed-swing diagnostic evidence (provisional)

**Status:** Diagnostic event comparison complete; **research acceptance NOT_ESTABLISHED**.
**Evidence reported by operator:** 2026-10-25. This record is a transcription of
operator-reported local outputs and screenshots, **not** an independent inspection
of the local bytes, a platform execution attestation, or an independent signoff.
PR #12 remains draft and should not be merged on this evidence alone.

## Test scope

| Field | Operator-reported value |
| --- | --- |
| Symbol | TMF |
| Chart / snapshot aggregation | Daily |
| Snapshot first and last sessions | 2025-10-28 through 2026-10-23 |
| Snapshot bar count | 249 (zero-based indices 0–248) |
| Python reference | `technical_engine.structure.confirmed_swings` |
| Saved thinkScript reference | `thinkscript/TAE_Confirmed_Swings_Parity.ts` |
| Strategy exporter | `TAE_Swing_Event_Export`, user-run and separately configured |
| Swing parameters | left=2, right=2, tolerance_bps=0 |
| Capture file | `parity/tmf_001/tos_swing_capture_auto.csv` (local-only) |

**Sources and process:** A thinkorswim simulated-order OHLCV Strategy Report
was parsed into the normalized TAE input snapshot. Separate HIGH and LOW
simulated-order Strategy Reports were parsed and date-mapped against that frozen
snapshot into the six-column swing-event capture. Operator verified three
signals against the thinkorswim study/Data Box:

| Kind | Pivot index / session | Confirmation index / session | Price |
| --- | --- | --- | --- |
| HIGH | 160 / 2026-06-18 | 162 / 2026-06-23 | 36.93 |
| LOW | 162 / 2026-06-23 | 164 / 2026-06-25 | 35.21 |
| HIGH | 164 / 2026-06-25 | 166 / 2026-06-29 | 37.26 |

The automated converter's operator-reported metadata had zero verification
warnings. This is not sufficient evidence that the strategy exported *every*
eligible event independently of its position/order semantics.

## Diagnostic comparison result

The operator executed `uv run python scripts/check_tmf_swing_parity.py`:

```text
Python events: 68
thinkorswim events: 68
Matched events: 68
Differences: 0
Comparison complete: True
Research acceptance: NOT_ESTABLISHED
Export verification warnings: 0
Diagnostic only; platform execution not attested.
```

**Interpretation:** All supplied observations agree with Python's confirmed
swing event identities, sessions, and prices at the comparator tolerance. The
platform evidence is operator-supplied, and matching a report from a strategy
using the same rules does not by itself establish independent platform
attestation or full historical OHLCV correctness. No performance or
point-in-time trading claim follows.

## Precision / source-quality findings

- Data-quality audit: **170 of 249** bars were marked suspect because export
  volume had noninteger values. First flagged index/date: **79 / 2026-02-23**.
  The exported values `5607382.9196` (2026-02-23) and `4347081.8456`
  (2026-02-24) were observed to round to the thinkorswim Data Box's displayed
  integer volumes. This spot check does not establish volume provenance or
  explain the fractional part. Source values were not changed.
- OHLC precision audit (values beyond cents): **open 7, high 90, low 72,
  close 0**. Preserve original precision. Adjustment policy was reported
  as `unverified_chart_adjustments`; metadata reported
  `date_alignment_verified: false` and
  `full_bar_equivalence_verified: false`.
- **18 of 68** swing prices used sub-cent precision. An in-memory
  `ROUND_HALF_UP` cents-rounding scenario retained **68 events**, with
  **0 lost and 0 added event identities**, but changed the prices of 18
  matched events. This is sensitivity evidence only; a rounded dataset
  was not accepted or substituted.

## SHA-256 fingerprints (operator-reported local `sha256sum`)

These identify the source bytes the operator reported using. Recompute locally
before any acceptance decision; the raw licensed data should remain local.

| Local file | SHA-256 |
| --- | --- |
| `parity/tmf_001/StrategyReports_TMF_OHLCV.csv` | `cc0d099ab35859cb0106ff1959b7c14f97a96ed55fc3c75b314dc09f0dd3bdbe` |
| `parity/tmf_001/StrategyReports_TMF_HIGHS.csv` | `cd32c25e336d9e5c7660b922ca2c56a9a0fe2779776e1f5400b67bfe7de5ca84` |
| `parity/tmf_001/StrategyReports_TMF_LOWS.csv` | `e2471593958fa0b6de2b68f6a3f200aa71132caad41415c79cb838fa4240fb98` |
| `parity/tmf_001/input_snapshot.json` | `3e66815197ee60b68489306d61dad8462cd1c25b92ec250dd72706e615add7e4` |
| `parity/tmf_001/tos_swing_capture_auto.csv` | `64651c7fcd6d9a3ec2aa90e8b7a9192e19c113c89f35591cbe2db328e95d3655` |
| `thinkscript/TAE_Confirmed_Swings_Parity.ts` | `ef187e67d5fbf2f12fb3eb74f55d22cb556f8f2b6f4ee2c6067cf2bd9818df49` |

The actual full saved `TAE_Swing_Event_Export` source used by the operator
is **not yet independently reconciled** or source-fingerprinted in this
evidence package. The local, untracked conversion/comparison scripts likewise
need versioned review before reproducibility signoff.

## Open acceptance work

1. Preserve the exact applied HIGH/LOW export strategy source, setting changes,
   report date range, relevant screenshots, and its SHA-256. Verify strategy
   `AddOrder` timing, simultaneous events, adjacent events, first/last
   confirmation bars, and any skipped or duplicated report records.
2. Review/export the three local helper scripts in a controlled, reproducible
   implementation change; do not simply commit the market-data directory.
3. Audit complete OHLC bar/date alignment (not just spot checks), chart
   price-adjustment settings, and original raw-source versus study source
   conventions. Do not infer historical knowledge timestamps from chart dates.
4. Resolve and document the 170 suspect volume observations separately.
   Swing parity consumes high/low only; this does not waive OHLCV provenance
   checks for downstream research.
5. Independently review fingerprints, metadata, raw local records and the
   comparator output. Record explicit reviewer disposition before promoting
   any milestone to accepted.

**Decision:** Candidate **68/68 cross-implementation diagnostic match**,
with event-identity stability under a limited rounding sensitivity test.
**TAE-TOS-001 research acceptance remains NOT_ESTABLISHED**. TAE-TOS-002
OnDemand, TAE-TOS-003 paperMoney, the other structure types, and ORCH remain
out of scope.
