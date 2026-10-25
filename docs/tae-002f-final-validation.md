# TAE-002F — final software-evidence validation gate

TAE-002F is a **read-only software-evidence audit** of the immutable
TAE-002E structure artifacts. It is not an independent certification of
predictive performance, historical live observability or strategy parity.

## Inputs and auditable gates

Call `validate_structure_run(directory)` on a previously generated
`structure-run-<sha256>` directory. It rejects non-directory inputs,
symlinks, missing or extra files, malformed/noncanonical JSON, unfamiliar
artifact versions or model versions, mismatched configuration hashes, output
hashes, byte lengths, input fingerprints, counts, run IDs and directory
names. It does not repair or overwrite evidence.

It parses the frozen input snapshot using the TAE-001 data contract and
reconstructs the complete TAE-002E configuration. It independently invokes
TAE-002A through TAE-002D ledger-producing functions, compares the
canonical output bytes, and checks all recorded timestamp constraints.
For **every** input prefix it recomputes four event streams and requires that
they exactly match the full-ledger events available by that prefix. This
exhaustive check can be costly on large datasets; no partial pass is
represented as exhaustive verification.

The immutable report contains source and manifest identity, event counts,
number of prefix comparisons, number of event records whose recorded
knowledge time postdates the observed session, and separate software
integrity/replay/prefix verification flags.

## What passing does not mean

`research_acceptance` stays `NOT_ESTABLISHED` even on a passing run.
Successful software validation does not establish that a modern historical
backfill was available for historical execution, that a financial hypothesis
was preregistered, that benchmark comparisons are independent, or that any
technical structure predicts future returns. No thinkScript parity,
OnDemand historical replay, forward paperMoney experiment, ORCH integration
or trading authorization is attempted.

TAE-003's chronological performance investigation also remains unaccepted
as independent predictive evidence. Human review of provenance, archived
vintages, experimental design, and separate platform-validation reports is
still required. TAE-002F's implementation may be merged while its ultimate
independent research acceptance remains outstanding.

## Acceptance

Use `uv run --locked pytest -rs -q`, `uv run --locked ruff check .`,
`uv run --locked ruff format --check .`, `uv build`, and Windows/Linux CI.
Check tampering, validation failure without file mutation, source-provenance
consistency, causal prefix invariance and deterministic byte-for-byte replay.
