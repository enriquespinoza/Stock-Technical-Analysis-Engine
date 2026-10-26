# TAE-005C1 — Statistical inference methodology (review-gated proposal)

**Status:** PROPOSED / NOT APPROVED. **Research acceptance:** NOT_ESTABLISHED.
**Gate:** Methods-only; no inferential code, held-out outcome inspection, real-market claims, or changes to accepted TAE-001/002/003/005A/005B contracts. TAE-005C2 MUST NOT be merged before independent approval of this methodology. A Git merge alone is not preregistration.

## 1. Inputs and fixed study contract

Re-use TAE-003 `ForwardReturnLabel` outcomes and TAE-005B's *event-time* feature-eligible BREAKOUT cohort, context flags, censoring, fixed cutoffs, and fingerprint. Require a registered study ID, frozen snapshot hashes, software revision, exact symbolic universe, exchange calendar, point-in-time source-vintage policy, partitions, observation horizons, embargo and all tested arms. Historical modern backfills are **retrospective** even when chronologically split. No TMF data is accessed by C1.

**Study-specific decisions that must be externally fixed prior to holdout access:** population/universe and timeframe, horizon set, maximum horizon, decision/availability time, block length, number of blocks and draws, minimum sample size, missingness rule, exact event grouping and multiplicity scope. This proposal defines default candidate rules below; those decisions require approval and cannot be tuned after seeing holdout results.

## 2. Confirmatory hypotheses and estimands

For each prespecified horizon `h`, compare each TAE-005B arm with the **same-horizon, feature-eligible, matured unfiltered baseline**. Arms in the single family: `ALL_CONTEXTS`, `WITHOUT_RSI`, `WITHOUT_EMA`, `WITHOUT_MOMENTUM`, `WITHOUT_ATR`. The existing unfiltered arm is a **reference**, not an additional hypothesis. Both upward and downward BREAKOUT events are eligible, using the fixed directional-return sign convention.

- Primary estimand `Delta[a,h]`: mean directional close-to-close return among the events selected by arm `a`, **minus** the mean directional return among all feature-eligible breakout events for horizon `h`, both measured in the same predefined holdout period. Arm subsets are **not randomly assigned**, so `Delta` measures association/selection, not causal incremental value.
- Null `H0[a,h]: Delta[a,h] <= 0` versus directional `H1[a,h]: Delta[a,h] > 0`. The positive direction is a proposed candidate and must be frozen before holdout evaluation. A nonpositive or inconclusive estimate does not validate a positive edge.
- Optional exploratory contrasts (e.g., `WITHOUT_RSI - ALL_CONTEXTS`) are not part of this confirmatory family. They must be labeled exploratory unless a new preregistration adds them and expands the multiplicity family.
- Every horizon and arm pair counts as one hypothesis. A 3-horizon plan with five arms yields 15 confirmatory tests, not 5. Never select horizons after looking at holdout outcomes.

## 3. Sampling and dependence

The observational unit is a matured `(symbol, breakout event ID, observation index, horizon)` label; it is **not** an independent sample. Multiple events can share breakout IDs, overlap future return windows, and co-move on market dates. A symbol-level, calendar-aligned event ledger across all instruments is required for cross-sectional inference. A single-symbol input can be evaluated only as a single-symbol retrospective study; cross-symbol generalization is prohibited.

**Candidate dependence procedure:** resample consecutive calendar/session blocks from the *holdout session timeline*, jointly across all symbols, using a deterministic stationary/circular block bootstrap with shared block draws for all arms and hypotheses. Keep all event records and their outcome values together under the event-start block assignment; never independently draw filter-selected and baseline observations. Holdout label endpoints must be inside the TAE-003 maturity boundary. Require block length at least the maximum tested horizon and a justification for longer serial dependence; overlap alone does not establish that this captures all dependence. The number of independent calendar blocks, cluster concentration and sensitivity to block length must be reported. If a trustworthy common exchange-session calendar is unavailable, block resampling must fail closed.

Compute the selected-arm and unfiltered means from each **shared** resample, including their overlap, rather than treating them as independent sample means. Undefined bootstrap arms (zero selected events) must be counted explicitly; they are never assigned zero or silently discarded. Define a hard abort criterion for an excessive undefined-draw fraction before C2 implementation.

The bootstrap method must be assessed with controlled dependent-null simulations for coverage and familywise false-positive rates before real-data interpretation; simulation calibration cannot by itself establish its validity for actual markets.

## 4. Multiple testing, uncertainty and decisions

**Candidate default error rate:** familywise alpha=0.05, **one-sided**, across every registered arm × horizon. The primary proposed procedure is simultaneous max-statistic studentized bootstrap with a common resample schedule and null-centered contrasts. Calibration must control dependence among overlapping arms, symbols and horizons; variance estimators and small-sample behavior require simulation validation. If this fails calibration, revert to a conservative, documented Bonferroni/Holm familywise procedure *only after revising and reapproving the specification*; never swap methods after holdout inspection.

Report observed contrasts, baseline and arm means, eligible/matured/censored counts, bootstrap standard errors, adjusted one-sided p-values and simultaneous lower confidence bounds (or `None` where undefined), random generator algorithm/seed, block policy, draw count, software and source hashes. Any point estimate or unadjusted result remains **descriptive** unless all gates pass.

A statistically positive contrast does NOT assert profitability, transportability, a trading fill, or causality. Do not conflate a one-sided bound with a two-sided confidence interval.

## 5. Mandatory INCONCLUSIVE / invalid conditions

Fail closed without declaring statistical superiority if any of these hold:

1. No externally approved and timestamped preregistration, or an inconsistent/unreproducible plan hash; a local hash alone is insufficient.
2. Unverified provider source versions, source availability/decision time, corporate-action adjustment, security universe, or date alignment for a claimed point-in-time study. A modern backfill must remain marked retrospective.
3. Outcome or feature leakage; any violation of TAE-003 partitions, embargo, maturity, warmup eligibility or fixed context thresholds.
4. Insufficient matured observations in either arm or baseline, too few distinct event groups or eligible calendar blocks, high dependence concentration, or bootstrap resamples with too many undefined arms. Exact numeric thresholds must be registered before execution.
5. Missing calendar alignment or unverifiable same-session synchronization across a multi-symbol universe.
6. Degenerate, nonfinite, or numerically unstable bootstrap statistics; inadequate null simulation calibration, failed interval coverage, or familywise error control.
7. Unexpected exclusions/censoring or missingness that violates the registered selection rules; no silent dropping, filling, or reassignment.
8. Unregistered tests, post hoc threshold searches, altered horizons, duplicate hypothesis IDs, or changed multiplicity family.
9. Unreconciled data fingerprints, suspected misadjustment, unreviewed provider-vintage revisions, or an incomplete independent evidence audit.

Insufficient evidence is **INCONCLUSIVE**; data-contract violation is **INVALID**. Neither equals a negative hypothesis result, and neither may be converted to a positive result.

## 6. Approval checklist before TAE-005C2

An independent methodology reviewer must explicitly sign off on: (a) all estimands and nulls, (b) the comparison family and one-sided direction, (c) dependence and calendar clustering, (d) bootstrap choice/block policy/draw count, (e) adjusted inference and calibration performance criteria, (f) minimum arm and block counts and missingness/undefined-draw thresholds, (g) deterministic PRNG and serialized output schema, (h) retrospective/pit-point-in-time limitations, and (i) closed-world treatment of exploration and potential amendments.

**Gate result: OPEN.** Until these numeric/technical decisions and reviewer approval are recorded, C2 is a tracked assignment only. No real TMF/holdout data is to be used for tuning this methodology.
