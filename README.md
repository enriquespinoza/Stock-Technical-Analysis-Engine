# Stock Technical Analysis Engine

TAE-001 provides a Python 3.11 foundation for **research-only** daily OHLCV
validation, deterministic technical indicators and immutable research artifacts.
It contains no order placement, brokerage execution, scoring or model training.
The separate `Systematic-Trading-Research-Platform` remains the orchestrator.

## Development

Install [uv](https://docs.astral.sh/uv/) and run from this repository:

```bash
uv python install
uv sync --frozen --all-extras
.venv/bin/python --version
.venv/bin/pytest
.venv/bin/ruff check .
.venv/bin/ruff format --check .
uv build
```

The runtime uses only the Python standard library. `uv.lock` locks development
dependencies. Python 3.11 is intentional; the package rejects other minor versions.
All tests run offline using deterministic synthetic inputs. No Schwab account,
API key, external service or sibling repository is required.

## Generate a reproducible research run

```bash
.venv/bin/python scripts/generate_fixture.py --output data/synthetic.json
.venv/bin/python -m technical_engine \
  --input data/synthetic.json \
  --config config/default.json \
  --output reports \
  --run-at 2025-01-02T00:00:00Z
```

The fixture has 280 synthetic weekday sessions. It is not an exchange calendar or
market dataset. Its retrieval timestamp is fixed at January 1, 2025. `--run-at`
must be timezone-aware and at or after all source availability/retrieval times;
an explicit timestamp makes exact reruns reproducible. For real research, use the
actual capture/run time and retain the original source snapshot.

The command prints a `reports/run-<SHA256>/` path containing:

| File | Purpose |
| --- | --- |
| `features.csv` | One row per session, provenance and technical features |
| `feature_metadata.json` | Formula conventions, units, windows and warm-up rules |
| `data_quality.json` | Validation results and warnings |
| `input_snapshot.json` | Normalized input with full source and action provenance |
| `manifest.json` | Engine version, configuration, input/output hashes and timestamps |

Exact reruns verify and reuse the existing bytes. Different runs receive distinct
directories. Changed, extra or missing historical files cause a failure rather
than an overwrite. Investigate stale `.artifact-write.lock` directories before
removing them; a writer may still be active. Output publication is atomic for
cooperating writers on a local filesystem, without a crash-durability guarantee.

`data/` and `reports/` are excluded from Git except for directory placeholders.
Do not commit licensed datasets, credentials or generated research histories.

## Input contract

`technical_engine.data.OHLCVDataset` contains an immutable tuple of `OHLCVBar`
records plus a snapshot identifier. `to_dict()` and `from_dict()` provide the
versioned JSON boundary used by the CLI. Each bar contains:

- Symbol and trading-session date; open, high, low, close and nonnegative volume.
- Provider, snapshot ID and an explicit price-adjustment policy.
- Timezone-aware source retrieval and exact-value availability timestamps.
- Quality status (`valid`, `suspect` or `invalid`) and structured corporate-action
  records when supplied, including optional factors, amounts and knowledge times.

Validation rejects duplicate/out-of-order sessions, mixed provenance, invalid
prices and OHLC relationships, nonfinite/missing values, missing timestamps and
insufficient requested history. It flags zero volume and suspect observations.
An absent action record means none was supplied, not proof that no action occurred.
Use `validate_dataset(dataset, min_history=200, expected_sessions=calendar)` when a
study requires a particular history/calendar. Without a supplied calendar, missing
exchange sessions cannot be inferred reliably.

`technical_engine.providers.schwab.normalize_price_history()` converts an already
retrieved Schwab daily-candle response. The caller supplies the session timezone,
availability/retrieval timestamps, snapshot ID, adjustment policy and any action
metadata. It does not fetch data, authenticate, guess split treatment or repair
source errors. A live Schwab client is outside this sprint.

## Features and timing

`IndicatorConfig` and `config/default.json` version all parameters. Defaults are
SMA 20/50/200, EMA 9/21/50, Wilder RSI 14, MACD 12/26/9, Wilder ATR 14,
20-return annualized realized volatility, percent ROC 5/10/20, relative volume
against 20 strictly prior sessions, and prior 20-session highs/lows.

EMA uses an SMA seed. Flat RSI is 50; one-sided gains/losses produce 100/0.
ATR seeds with the mean of the first 14 true ranges, using first-bar high minus
low. Volatility uses sample standard deviation of log returns and a configurable
252-session annualization. A zero relative-volume baseline is undefined.
Warm-up/undefined values remain `None` in Python and empty in CSV. Short histories
are retained; unavailable features stay missing. See metadata for exact first-valid
indices and formulas rather than assuming every feature warms up identically.

Features involving a session's close, high, low or volume require that information
to be available. `feature_available_at` conservatively covers the input prefix;
the caller remains responsible for truthful source timing and historical revisions.
Prefix tests prevent calculations from using later rows. They do not establish
that a provider's adjusted history was available in that form in the past.

See [architecture](docs/architecture.md) for boundaries, audit and artifact semantics,
and [research policy](docs/research-policy.md) for evidence and review requirements.
