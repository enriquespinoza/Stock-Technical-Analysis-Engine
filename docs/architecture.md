# Phase 1 architecture

The Technical Analysis Engine is an independent, research-only feature producer.
`Systematic-Trading-Research-Platform` remains the top-level orchestrator. This
repository neither changes it nor defines an interface for its inaccessible code.
The versioned artifact contract below is a proposed exchange boundary for later
integration review, not a claim of tested orchestrator compatibility.

## Boundaries

1. A provider retrieves source material outside analytical code. Phase 1 includes
   no authenticated retrieval client or live network requirement.
2. A provider normalizer converts an already supplied response into the immutable
   `OHLCVDataset` contract. The Schwab adapter accepts daily price-history candles;
   provider-specific millisecond timestamps do not enter indicator calculations.
3. Dataset validation checks provenance, temporal fields, finite prices, OHLC
   relationships, nonnegative volume, uniqueness and chronological ordering. It
   reports quality issues without silently dropping, sorting or imputing data.
4. Pure indicator functions consume validated data and a versioned configuration.
   Incomplete rolling windows yield missing feature values, not fabricated history.
5. The artifact writer records features, metadata, normalized source provenance,
   quality findings and a manifest in an immutable run directory.
6. An external orchestrator can inspect manifests and hashes before consuming
   outputs. No orchestrator integration or execution path is implemented here.

## Data and time

A dataset represents one symbol, provider, adjustment policy and input snapshot.
Bars identify trading sessions separately from timezone-aware retrieval and
availability timestamps. Session dates alone cannot establish a decision time.
Callers must supply honest availability and adjustment provenance; a current
provider download cannot establish what adjusted history looked like in the past.
The normalizer never invents a corporate-action adjustment or availability time.

The caller supplies the exchange/session timezone to Schwab normalization.
Completeness across exchange holidays requires an explicit expected-session
calendar; weekdays alone are not a reliable trading calendar. Duplicate and
out-of-order observations are invalid even when a caller could sort them.
No implicit forward fill, zero-price substitution or split correction occurs.

Current-session close, high, low and volume features become usable only after
those observations are available. The artifact format retains source timestamps
and a conservative feature availability time covering the input prefix. Prior
high/low and relative-volume baseline windows exclude the current observation;
their comparisons can still require current-session inputs. Prefix invariance
tests verify that later observations do not change earlier feature values.
Historical revisions, survivorship and provider restatements require separate
point-in-time datasets; indicator prefix tests cannot resolve those data issues.

## Numerical contract

Calculations use Python binary64 floats without rounding analytical outputs.
Missing warm-up values serialize as JSON null or empty CSV fields, never NaN or
infinity. `feature_metadata()` records formulas, units and warm-up requirements.
Parameters and formula conventions are versioned; changing a convention requires
an engine/configuration version change and new research outputs.

The baseline conventions are SMA-seeded EMA; Wilder RSI and ATR; log-return
sample standard deviation annualized by the configured sessions per year; percent
ROC; current volume divided by the mean of strictly prior volumes; and strictly
prior rolling high/low. Flat RSI is 50. A zero relative-volume baseline is missing.
These are research definitions, not empirically validated predictive signals.

## Artifact boundary

Each run records the engine version, full configuration and its digest, canonical
normalized input and its digest, optional original input-byte digest, explicit run
time and output digests. The manifest itself is not included in its own digest
set. Reproduction requires the same normalized input, original bytes when supplied,
configuration, engine version and explicit timestamp. Equivalent JSON with different
source bytes can intentionally have a different raw-input hash.

Content-derived run directories prevent accidental historical overwrite. A repeat
of an identical run verifies existing bytes; a collision with incomplete or changed
files fails. Do not edit a completed run to correct data. Produce a new snapshot and
a new run instead. External storage, retention, signing and orchestrator schema
negotiation remain future integration work.

## Repository audit (TAE-001)

The initial checkout was an unborn `work` branch with no tracked or untracked
project files. A read-only `git ls-remote origin` succeeded and returned no refs,
including no `main`. There were no dependency declarations, tests, architecture,
Schwab adapters, normalization contracts or agent instructions to preserve. No
sibling project checkout was present under `/workspace`; sibling APIs were not
invented. The requested foundation therefore introduced no existing-code conflict.
Work began on `feature/tae-001-foundation`. A hosted PR requires a real base branch.
