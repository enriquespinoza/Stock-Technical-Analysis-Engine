# TAE-002E: immutable market-structure research artifacts

`technical_engine.structure_artifacts.generate_structure_artifacts` publishes a **separate**
versioned evidence family for TAE-002A confirmed swings, TAE-002B support/resistance
level events, TAE-002C trend events, and TAE-002D breakout/retest/failed-breakout
events. It deliberately leaves TAE-001's `generate_artifacts`, directory naming,
manifest layout, and published feature schema unchanged.

## Contract and provenance

- Caller supplies a validated single-snapshot `OHLCVDataset`, `output_root`, and an
  explicit timezone-aware `run_at`. `run_at` cannot precede any source bar's
  availability or retrieval timestamp.
- `StructureArtifactConfig` freezes one shared `SwingConfig` and all downstream
  level, trend, breakout, retest and follow-up parameters. Defaults correspond
  to the independently tested research modules.
- The four event ledgers are serialized as arrays of complete dataclass records,
  including *pivot versus confirmation* indices and timestamps, source
  `available_at` and `retrieved_at`, conservative `usable_at`, and source
  `snapshot_id` where provided by the underlying event contract.
- Date/time fields are ISO 8601 text; input snapshots preserve their original
  timezone offsets. The run's `run_at` is normalized to UTC. Output JSON uses
  canonical sorted-key UTF-8 encoding and rejects NaN and infinity.
- Each new run publishes exactly six files: `confirmed_swings.json`,
  `level_events.json`, `trend_events.json`, `setup_events.json`,
  `input_snapshot.json`, and `manifest.json`.
- The manifest identifies schema family and version, model version, run time,
  complete configuration plus its SHA-256, input identity and snapshot SHA-256,
  event counts, and SHA-256/byte lengths for each output. `run_id` hashes the
  canonical manifest body excluding `run_id` to avoid a self-referential hash.
- Directory naming is `structure-run-<run_id>`; it does not collide with the
  existing TAE-001 `run-<run_id>` namespace.

## Immutability and publication

A cooperating-writer mkdir lock (`.structure-artifact-write.lock`) is acquired
before publishing. A stale lock fails closed and requires operator review. Files
are written to a private staging directory and the entire directory is renamed
into place. This provides atomic visibility, not guaranteed crash durability.

Identical runs verify **every byte and file name** and reuse the same directory.
Changed parameters, captured inputs, or run timestamps create new run IDs. A
missing file, symlink, modified file, unexpected file or non-directory destination
fails closed instead of overwriting research evidence. Failure cleanup removes
only the writer's owned temporary directory and lock; pre-existing artifacts and
unrelated files are not modified.

The API does not expose a trading signal, promise live historical knowledge,
validate statistical value, claim stable identities across source snapshots,
or change the top-level research orchestrator. Exporting an event does not
prove that its historical classification would have been observable before
its recorded `usable_at`.

## Acceptance

Run `uv run --locked pytest -rs -q`, `uv run --locked ruff check .`,
`uv run --locked ruff format --check .`, and `uv build` on Windows and Linux.
Verify canonical byte-for-byte reproducibility, content hashes, schema/version,
configuration and source fingerprinting, UTC normalization, historical knowledge
times, no-overwrite behavior, writer locking, failed-publication cleanup, and
unchanged TAE-001 artifact files.
