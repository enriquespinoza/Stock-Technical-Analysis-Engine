# TAE-005B — Prespecified indicator-context ablation (draft)

**Status:** Candidate research software, not empirically accepted.
**Research acceptance:** `NOT_ESTABLISHED`.
**Dependencies:** Accepted TAE-003 forward-return labels, TAE-005A statistical-plan
fingerprints and TAE-001 feature calculations. No changes to those modules.

## Fixed and testable context rules

Use existing `BREAKOUT` events and one or more horizons fixed *before*
reading holdout outcomes. Every event is evaluated using indicator values
from its **observation bar**, never subsequent bars. Default feature windows
are fixed and all indicators must have completed warmup; incomplete events
are excluded from **every** treatment and baseline, so the event population
is comparable.

For UP events, the four prespecified positive contexts are:

| Context | Exact rule at setup observation close |
| --- | --- |
| RSI | Wilder RSI(14) >= 50 |
| EMA | close > EMA(9) > EMA(21) |
| ROC/MACD | ROC(10) > 0 and MACD(12,26,9) histogram > 0 |
| ATR regime | ATR(14) / close >= 0.02 |

For DOWN events, RSI < 50; close < EMA(9) < EMA(21);
ROC(10) < 0 and MACD histogram < 0. The ATR condition
remains nondirectional. All comparisons are strict except the explicitly
inclusive RSI-UP and ATR thresholds. Equality does not pass the other
directional thresholds. These cutoffs are *design choices*, not optimized
or validated empirical thresholds.

## Ablation and reference population

For each predeclared TAE-005A BREAKOUT kind/horizon and partition, produce
six descriptive rows: unfiltered **feature-eligible** baseline, all four
contexts required, and one leave-one-context-out row per context. The
comparison reports counts of feature-eligible, matured and censored labels,
mean directional close-to-close return, positive fraction, and difference
from the **same-cohort unfiltered** baseline.

**These are not matched-pair differences.** Every treatment is a subset
of baseline events and may differ in its observed/matured distribution.
A threshold crossing does not imply causation or show incremental predictive
contribution. The leave-one-out rows are not a causal isolation experiment.

All outcomes inherit TAE-003's cutoff purging, embargo and right censoring.
No p-values, trading profits, costs, fills, confidence intervals, or
multiple-testing significance claims are calculated. Dependence across
repeated breakout events, overlapping labels, regimes and securities remains.

## Provenance and claims

A canonical plan fingerprint binds the TAE-005A study fingerprint, fixed
indicator configuration, rule family order, and contract `tae-005b-v1`.
A separate SHA-256 identifies the complete input snapshot. Fingerprints do
not independently attest provider vintages or prove genuine preregistration.
Prespecified study approval must be externally recorded **before** looking
at held-out outcomes. Historical backfills are retrospective, not prospective.

This phase uses synthetic fixtures only; do not run it as an accepted
TMF study until bar equivalence, corporate-action normalization, provider
provenance, study and baseline definitions, and independent review gates
are satisfied. `TAE-TOS-001` diagnostic parity alone does not meet those gates.

## Software acceptance

Require Linux/Windows CI, synthetic edge-case tests, Ruff lint and format,
`uv build`, and independent review. The output is research diagnostics only,
with `research_acceptance="NOT_ESTABLISHED"`.
