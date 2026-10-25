"""Read-only TAE-002F software-evidence audit of TAE-002E structure runs.

Passing this gate does NOT accept research performance, establish historical
point-in-time vintages, verify thinkScript parity, or authorize ORCH integration.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from technical_engine._version import __version__
from technical_engine.artifacts import canonical_json, sha256
from technical_engine.data import OHLCVDataset
from technical_engine.levels import LevelEvent, level_events
from technical_engine.setups import SetupEvent, setup_events
from technical_engine.structure import ConfirmedSwing, SwingConfig, confirmed_swings
from technical_engine.structure_artifacts import (
    STRUCTURE_ARTIFACT_SCHEMA_VERSION,
    StructureArtifactConfig,
    _jsonable,
)
from technical_engine.trends import TrendEvent, trend_events

_STREAMS = (
    "confirmed_swings.json",
    "level_events.json",
    "trend_events.json",
    "setup_events.json",
)
_EXPECTED_FILES = {*_STREAMS, "input_snapshot.json", "manifest.json"}
_DATA_FAMILY = "TAE-002-market-structure"


@dataclass(frozen=True)
class StructureValidationReport:
    run_id: str
    snapshot_id: str
    manifest_sha256: str
    event_counts: tuple[tuple[str, int], ...]
    prefix_checks: int
    delayed_knowledge_events: int
    integrity_verified: bool = True
    deterministic_replay_verified: bool = True
    exhaustive_prefix_invariance_verified: bool = True
    research_acceptance: str = "NOT_ESTABLISHED"
    method: str = "software_artifact_audit_not_independent_research_validation"


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def _read_json(directory: Path, filename: str) -> tuple[Any, bytes]:
    path = directory / filename
    _require(path.is_file() and not path.is_symlink(), f"Unsafe artifact file: {filename}")
    raw = path.read_bytes()
    try:
        decoded = json.loads(raw)
        _require(canonical_json(decoded) == raw, f"Noncanonical artifact: {filename}")
    except (UnicodeDecodeError, ValueError, TypeError) as exc:
        raise ValueError(f"Invalid JSON artifact: {filename}") from exc
    return decoded, raw


def _config_from_manifest(value: Any) -> StructureArtifactConfig:
    _require(isinstance(value, dict), "Invalid manifest configuration")
    expected = {field.name for field in fields(StructureArtifactConfig)}
    _require(set(value) == expected, "Unexpected configuration fields")
    swing = value["swing"]
    _require(isinstance(swing, dict), "Invalid swing configuration")
    _require(
        set(swing) == {field.name for field in fields(SwingConfig)},
        "Unexpected swing configuration fields",
    )
    try:
        config = StructureArtifactConfig(**{**value, "swing": SwingConfig(**swing)})
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid structure configuration") from exc
    _require(_jsonable(asdict(config)) == value, "Configuration representation mismatch")
    return config


def _ledgers(
    dataset: OHLCVDataset, config: StructureArtifactConfig
) -> dict[
    str,
    tuple[ConfirmedSwing, ...]
    | tuple[LevelEvent, ...]
    | tuple[TrendEvent, ...]
    | tuple[SetupEvent, ...],
]:
    return {
        "confirmed_swings.json": confirmed_swings(dataset, config.swing),
        "level_events.json": level_events(dataset, config.level_config()),
        "trend_events.json": trend_events(dataset, config.trend_config()),
        "setup_events.json": setup_events(dataset, config.setup_config()),
    }


def _knowledge_check(dataset: OHLCVDataset, streams: dict[str, tuple[Any, ...]]) -> int:
    latest_available: list[datetime] = []
    latest_retrieved: list[datetime] = []
    for bar in dataset.bars:
        latest_available.append(
            max(latest_available[-1], bar.available_at) if latest_available else bar.available_at
        )
        latest_retrieved.append(
            max(latest_retrieved[-1], bar.retrieved_at) if latest_retrieved else bar.retrieved_at
        )
    delayed = 0
    for filename, events in streams.items():
        for event in events:
            index = (
                event.observation_index
                if filename == "setup_events.json"
                else event.confirmation_index
            )
            _require(0 <= index < len(dataset.bars), "Event index outside input snapshot")
            _require(event.snapshot_id == dataset.snapshot_id, "Wrong event snapshot")
            _require(
                event.usable_at >= max(latest_available[index], latest_retrieved[index]),
                "Event usable_at predates source knowledge",
            )
            _require(
                event.usable_at >= event.available_at and event.usable_at >= event.retrieved_at,
                "Event knowledge timestamps are inconsistent",
            )
            if filename == "setup_events.json":
                _require(
                    event.level_confirmation_index
                    < event.breakout_index
                    <= event.observation_index,
                    "Setup references an unconfirmed level or future breakout",
                )
                session = event.observation_session
            else:
                _require(
                    event.pivot_index <= event.confirmation_index,
                    "Swing-derived event predates its pivot",
                )
                session = event.confirmation_session
            if event.usable_at.date() > session:
                delayed += 1
    return delayed


def validate_structure_run(directory: str | Path) -> StructureValidationReport:
    """Verify all six files, their provenance, deterministic replay and EVERY prefix.

    Read-only. The audit intentionally fails closed on unknown schemas,
    mismatched model versions, tampering or incomplete publications.
    Exhaustive replay is computationally expensive on long histories.
    """
    run_directory = Path(directory)
    _require(
        run_directory.is_dir() and not run_directory.is_symlink(),
        "Run must be a regular directory",
    )
    paths = list(run_directory.iterdir())
    _require(
        {path.name for path in paths} == _EXPECTED_FILES,
        "Run has missing or unexpected files",
    )
    _require(
        all(path.is_file() and not path.is_symlink() for path in paths),
        "Run contains unsafe files",
    )
    parsed = {name: _read_json(run_directory, name) for name in _EXPECTED_FILES}
    manifest, manifest_bytes = parsed["manifest.json"]
    _require(isinstance(manifest, dict), "Manifest must be an object")
    _require(
        manifest.get("artifact_family") == _DATA_FAMILY
        and manifest.get("artifact_schema_version") == STRUCTURE_ARTIFACT_SCHEMA_VERSION,
        "Unsupported structure artifact family or schema",
    )
    _require(manifest.get("model_version") == __version__, "Model version mismatch")
    body = {key: value for key, value in manifest.items() if key != "run_id"}
    run_id = sha256(canonical_json(body))
    _require(manifest.get("run_id") == run_id, "Invalid content-addressed run ID")
    _require(run_directory.name == f"structure-run-{run_id}", "Incorrect run directory name")

    config_dict = manifest.get("configuration")
    config = _config_from_manifest(config_dict)
    _require(
        manifest.get("configuration_sha256") == sha256(canonical_json(config_dict)),
        "Configuration hash mismatch",
    )
    outputs = manifest.get("outputs")
    _require(
        isinstance(outputs, dict) and set(outputs) == _EXPECTED_FILES - {"manifest.json"},
        "Invalid output inventory",
    )
    for filename, details in outputs.items():
        _require(
            details
            == {
                "sha256": sha256(parsed[filename][1]),
                "bytes": len(parsed[filename][1]),
            },
            f"Output integrity mismatch: {filename}",
        )

    dataset = OHLCVDataset.from_dict(parsed["input_snapshot.json"][0])
    input_info = manifest.get("input")
    _require(isinstance(input_info, dict), "Invalid input provenance")
    _require(
        input_info
        == {
            "snapshot_id": dataset.snapshot_id,
            "normalized_sha256": sha256(parsed["input_snapshot.json"][1]),
            "symbol": dataset.bars[0].symbol,
            "provider": dataset.bars[0].provider,
            "adjustment_policy": dataset.bars[0].adjustment_policy,
            "bar_count": len(dataset.bars),
            "first_session": dataset.bars[0].session.isoformat(),
            "last_session": dataset.bars[-1].session.isoformat(),
        },
        "Input snapshot or metadata mismatch",
    )
    try:
        stamp = datetime.fromisoformat(manifest["run_at"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Invalid run_at") from exc
    _require(
        stamp.tzinfo is not None and stamp.utcoffset() is not None,
        "run_at must be timezone-aware",
    )
    _require(stamp.astimezone(UTC).isoformat() == manifest["run_at"], "run_at not canonical UTC")
    _require(
        all(max(bar.available_at, bar.retrieved_at) <= stamp for bar in dataset.bars),
        "Run predates recorded source knowledge",
    )

    full = _ledgers(dataset, config)
    counts = manifest.get("record_counts")
    _require(isinstance(counts, dict) and set(counts) == set(_STREAMS), "Invalid event counts")
    for filename, events in full.items():
        _require(isinstance(parsed[filename][0], list), f"Ledger is not a list: {filename}")
        _require(counts[filename] == len(events), f"Event count mismatch: {filename}")
        expected = canonical_json(_jsonable([asdict(event) for event in events]))
        _require(parsed[filename][1] == expected, f"Deterministic replay mismatch: {filename}")

    delayed = _knowledge_check(dataset, full)
    for size in range(1, len(dataset.bars) + 1):
        prefix = replace(dataset, bars=dataset.bars[:size])
        observed = _ledgers(prefix, config)
        for filename in _STREAMS:
            event_key = (
                "observation_index" if filename == "setup_events.json" else "confirmation_index"
            )
            before = tuple(event for event in full[filename] if getattr(event, event_key) < size)
            _require(
                observed[filename] == before,
                f"Lookahead or prefix-replay divergence: {filename} at size {size}",
            )
    return StructureValidationReport(
        run_id=run_id,
        snapshot_id=dataset.snapshot_id,
        manifest_sha256=sha256(manifest_bytes),
        event_counts=tuple((name, len(full[name])) for name in _STREAMS),
        prefix_checks=len(dataset.bars) * len(_STREAMS),
        delayed_knowledge_events=delayed,
    )
