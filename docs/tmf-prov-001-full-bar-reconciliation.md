# TMF-PROV-001 — qualified-source OHLCV reconciliation (software candidate)

**Research acceptance: `NOT_ESTABLISHED`.** A successful script run is a
reproducible operator-side comparison, not independent market-data attestation.
This tool does not fetch or repair historical data and does not produce
point-in-time trading evidence.

## Inputs, maintained locally

Place these already captured files in the ignored `parity/tmf_001/` directory:

| Path | Role |
| --- | --- |
| `StrategyReports_TMF_OHLCV.csv` | Original 249-bar thinkorswim Strategy Report; audited SHA-256 built into the verifier |
| `tmf_daily_ohlcv.csv` | Converted six-field OHLCV table |
| `input_snapshot.json` | Frozen engine snapshot |
| `source_metadata.json` | Original/snapshot hashes and unverified chart adjustment policy |
| `reference/tiingo/tmf_eod_original.json` | Original Tiingo response bytes containing raw and adjusted OHLCV |
| `reference/tiingo/manifest.json` | HTTP 200, retrieval timestamp, ticker/date range, count and response SHA-256 |
| `platform_sources/TAE_TMF_OHLCV_Export.ts` (optional) | Recovered thinkScript *candidate*; hash-check if present, never treat as proof that code ran at capture |

The original TMF source report hash expected by the script is
`cc0d099ab35859cb0106ff1959b7c14f97a96ed55fc3c75b314dc09f0dd3bdbe`.
It is intentionally **not** derived from the mutable metadata file. Other
inputs are also hash-checked against their manifests. Any mismatch fails
without writing a new report. Do not alter old captures to satisfy a check.
The optional recovered exporter candidate is checked against the operator's
reported SHA-256 `d41ece8f8c18c3fe5ef13c7da03acf1bf1a30f717a8348378441f4e39dc6ab49`.
Absence is reported, not silently interpreted as a platform attestation.

On Windows Git Bash from the repository root, with the previously configured
external `UV_PROJECT_ENVIRONMENT` or other functional virtual environment:

```bash
uv run --frozen python scripts/reconcile_tmf_ohlcv.py --no-write
```

After checking aggregate results, create a deterministic content-addressed
local report (repeat runs with identical inputs are idempotent; differing
contents at the same path fail closed):

```bash
uv run --frozen python scripts/reconcile_tmf_ohlcv.py
```

Output under `parity/tmf_001/reconciliation/run-<sha256>/`:

- `summary.json`: input fingerprints, exact field-match counts, volume
  discrepancy categories and unresolved evidence status.
- `per_session_ledger.json`: all 249 dates, signed raw-price deltas, volume
  deltas/ratios and **descriptive**, not causal, discrepancy classifications.

The detailed ledger is *licensed-data-derived* and **must remain local**.
The entire `parity/tmf_001/` directory is ignored by Git. Verify exclusion
with `git check-ignore -v parity/tmf_001/reference/tiingo/tmf_eod_original.json`.
Do not upload the ledger, original vendor response, authentication headers,
`.env`, platform screenshots or other licensed records to GitHub/Notion.

## What the comparator verifies

1. Source report and snapshot match recorded SHA-256 values; Tiingo response
   matches the acquisition manifest, successful JSON status and UTC-stamped
   retrieval time. It checks neither provider license nor source independence.
2. The original report has 249 OHLCV Buy-to-Open records and 249 export exits.
   Every report trade date maps in order to the converted session; all five
   values are reconstructed with `Decimal` and checked numerically.
3. Converted CSV equals the frozen input snapshot, in both session order and
   all 1,245 OHLCV observations.
4. All 249 reference session dates agree exactly with source sessions. This
   date-set match is not a separate exchange-calendar completeness attestation.
5. All 996 prices compare exactly against Tiingo raw and, separately,
   dividend-adjusted prices. There is **no automatically applied tolerance**.
6. All volume differences are categorized by sign and magnitude: exact,
   sub-share (absolute difference under 1 share), intermediate (1 to under
   100 shares), or material (100 shares or more). Rounding/truncation match
   counts are **sensitivity diagnostics** and never rewrite the original.
7. The resulting ledger retains per-session exceptions for a qualified
   independent reviewer. The script always sets platform verification,
   full-bar equivalence and research acceptance to *unverified/not established*.

## Prior operator-reported comparison (not rerun here)

With original TMF evidence dated 2026-10-25 and a Tiingo reference captured
separately, the operator reported:

- 249/249 matched sessions and 992/996 exact raw OHLC values (four field
  differences on 2026-01-14 and 2026-02-12).
- 73/249 exact volume matches, 156 positive sub-share discrepancies, and
  20 differences of at least 100 shares; no negative differences.
- All 170 fractional local volumes begin on 2026-02-23. Thirteen material
  volume discrepancies occur consecutively on 2026-10-07 through 2026-10-23.
- Four nonzero Tiingo dividend records and zero non-unit split factors in
  the compared interval.

These findings must be reproduced with the committed comparator against the
operator's local evidence. They do **not** establish why differences exist.
The recovered 639-byte thinkScript OHLCV exporter uses next-bar `[-1]`
references in simulated-order labels, but its 2026-10-30 recovery timestamp
does not prove the same exact code ran at the 2026-10-25 capture. It does not
control dividend-adjustment settings, data-source price type or aggregation
convention. Retrospective export labels cannot establish historical point-in-
time availability.

## Independent reviewer still required

- Re-run byte-integrity audit (including original thinkScript source identity)
  and inspect the date-keyed discrepancy ledger without modifying evidence.
- Attest the original thinkorswim platform session/chart configuration and
  corporate-action policy, particularly dividend treatment and volume scope.
- Adjudicate the two price discrepancy sessions and all 20 material volume
  differences using defensible provider evidence; investigate the separate
  156 sub-share serialization differences.
- Evaluate whether volume-sensitive research must be excluded and preserve a
  dated reviewer decision with unresolved exceptions and original hashes.

Until all blocking fields are independently resolved, issue #17 stays open
and `research_acceptance = NOT_ESTABLISHED`, regardless of software test results.

## Software validation

```bash
uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked python -m build
```

Tests use synthetic 3-session fixtures only; no actual TMF market data is
stored in the repository or CI artifacts.
