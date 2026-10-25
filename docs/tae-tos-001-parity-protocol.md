# TAE-TOS-001 — Python / thinkScript signal-parity protocol (phase 1)

**Status: protocol and comparator implemented; no independently captured
thinkorswim observations and no published parity study accepted.**

This phase begins with *confirmed swing* observations from TAE-002A.
Support/resistance, trend and breakout parity require separately versioned
reference studies and acceptance cases. No TAE-002F signoff, OnDemand
replay, paperMoney forward result, strategy performance or ORCH contract
is implied.

## Input normalization and platform procedure

The operator must select the identical symbol, adjustment policy, daily
session sequence, OHLC values and explicit swing left/right and bps
tolerance on both platforms. Platform chart price adjustments, aggregation,
time zone, truncated history, loading limits and repaint behavior must be
recorded and reviewed. thinkScript must confirm a swing only on or after
the right-side confirmation bar. The pivot is back-dated for visual
annotation only; it is not an available signal at the pivot session.

The comparison CSV must contain exactly these columns in this order:

```csv
kind,pivot_index,confirmation_index,pivot_session,confirmation_session,price
```

Positions are **zero-based in the complete frozen TAE input snapshot**,
not arbitrary chart indices. A missing event cannot be represented by a
zero price. Confirmations must occur strictly after pivots, and dates must
be canonical ISO session dates. HIGH and LOW are the only allowed kinds.
The event stream must be manually recorded from independently executed
study observations; never populate it from Python expectations for a
claimed parity study.

The operator-supplied `ThinkScriptCapture` identifies the recorded symbol,
daily aggregation, dataset SHA-256, exact study source SHA-256, bar count,
first/last session and capture timestamp. These fields are audit metadata;
they are **not cryptographic platform attestation**.

## Comparator and acceptance limits

`compare_swing_capture` recomputes the Python ledger, refuses mismatched
snapshot/chart metadata and malformed or duplicate capture rows, and reports
missing, extra, session-mismatched and price-mismatched identities. Absolute
price tolerance is explicit and defaults to 1e-8. Records are immutable;
results are deterministic.

A matching **synthetic** CSV demonstrates only comparator correctness.
Even a byte-consistent externally supplied CSV does not independently
verify that thinkorswim ran the study; `platform_execution_verified`
remains false and `research_acceptance` is always NOT_ESTABLISHED.
An accepted parity study requires documented study source and settings,
verified source dataset, actual thinkorswim observation capture, review of
all discrepancies and signoff from an independent reviewer.

## Research governance and next stages

A thinkScript reference implementation and a practical capture mechanism
are still required before genuine comparisons can be undertaken.
This module deliberately does not fabricate that evidence or imply that
the platform exposes an automated CSV event export API.

TAE-TOS-002 (historical OnDemand replay) and TAE-TOS-003 (forward
paperMoney evaluation) remain separate planned experiments.
No TAE-002F status, TAE-003 performance status, or ORCH integration
acceptance changes as a result of this protocol.
