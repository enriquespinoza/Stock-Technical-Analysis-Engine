# TAE-005A — Frozen statistical protocol and dependence audit

**Status:** Candidate research software, not approved or merged.
**Source:** Accepted TAE-003 `forward_evaluation.evaluate_forward_returns`.
**Research acceptance:** `NOT_ESTABLISHED`.

## Why this milestone exists

The six-paper research gap review identified that descriptive technical-analysis
examples are insufficient evidence of predictive validity. The engine already
contains causal setup-event generation and retrospective, horizon-purged
forward-return labels. TAE-005A deliberately audits their statistical
interpretability **before** implementing or searching for profitable filters.

## Scope and fixed hypotheses

The `StatisticalProtocolPlan` binds a named study to the complete TAE-003
`ForwardEvaluationConfig`, including its chronological cutoff, observation
horizons, embargo and setup configuration. An ordered tuple of distinct
`StatisticalHypothesis` records selects explicit event-kind/horizon slices.
Only the existing `BREAKOUT`, `RETEST`, `FAILED_BREAKOUT` event kinds
and directional close-to-close return outcome are supported initially.

The plan fingerprint is canonical SHA-256 of the plan and contract ID.
**Hashing a plan does not prove preregistration:** approval, external timestamp,
a signed reviewer identity and the fact the holdout was not inspected must be
documented separately *before* any claimed confirmatory evaluation.

No RSI, EMA, MACD, ATR or Bollinger filtering is included at this stage.
Candidates H1–H4 from the literature synthesis require a separate, reviewed
event-time filter definition and prespecified comparison baseline.

## Audit outputs

`audit_statistical_protocol(dataset, plan)` calls accepted TAE-003 and
returns immutable, deterministic rows for each hypothesis and each partition
(`DEVELOPMENT` and `HOLDOUT`). Each row contains:

- Matured and right-censored label counts; censored labels never become
  zero returns.
- Arithmetic mean directional return and positive fraction, both `None`
  when no matured labels are present.
- Distinct `breakout_id` count.
- Pair counts for overlapping **future** return windows (observation index,
  label end index] and for shared `breakout_id`.
- Number of connected components after linking all matured labels that
  share a breakout ID or have overlapping future windows.

These components flag visible event dependence; they are **not** independent
samples or a statistically valid effective sample-size estimate. Events with
disjoint windows can still be market-correlated.

The audit records a canonical snapshot SHA-256 from the validated dataset
plus plan SHA-256. It neither alters TAE-001 frozen data nor publishes raw
market data. It does not create or overwrite artifacts.

## Inference deliberately withheld

No p-values, confidence intervals, bootstrap significance, adjusted multiple
comparison thresholds, economic edge estimates, fill prices or transaction-cost
claims are supplied in TAE-005A. Future inferential work requires reviewed
assumptions for serial dependence (e.g. symbol-aware blocks), minimum sample
size, benchmark choice, multiple-testing control, universe and regime
selection, survivorship and historically available data. TAE-003's close-to-
close return following an event observed at the close is not an executable fill.

**No held-out evaluation can be called prospective on a modern backfill.**
Every result is labelled retrospective; every row has
`inference_status="NOT_ESTABLISHED"`.

## Software acceptance gate

Require synthetic tests covering plan validation, deterministic fingerprints,
the exact TAE-003 label slices, censoring, immutability, overlapping and
shared-breakout dependencies, plus Windows and Linux CI:

```bash
uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked ruff format --check .
uv build
```

Software review and research acceptance are separate decisions. Do not
change accepted TAE-003 or upstream event generation to make tests pass.
