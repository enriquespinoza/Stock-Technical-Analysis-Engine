"""Deterministic, immutable research artifacts with explicit temporal provenance."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from technical_engine._version import __version__
from technical_engine.data import OHLCVDataset, require_valid_dataset, validate_dataset
from technical_engine.indicators import IndicatorConfig, compute_features, feature_metadata

ARTIFACT_SCHEMA_VERSION = "1.0.0"


def canonical_json(value: Any) -> bytes:
    """Serialize exact snapshot representations deterministically, without NaN/Infinity."""
    return (
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
        + "\n"
    ).encode("utf-8")


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


@dataclass(frozen=True)
class ArtifactRun:
    directory: Path
    run_id: str
    manifest: dict[str, Any]


def _utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _feature_csv(dataset: OHLCVDataset, features: list[dict[str, object]]) -> bytes:
    if len(features) != len(dataset.bars):
        raise ValueError("Feature row count does not match input snapshot")
    provenance = (
        "symbol",
        "session",
        "snapshot_id",
        "available_at",
        "retrieved_at",
        "feature_available_at",
        "quality_status",
    )
    feature_keys = sorted(key for key in features[0] if key not in provenance)
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=[*provenance, *feature_keys], lineterminator="\n")
    writer.writeheader()
    prefix_available_at = dataset.bars[0].available_at
    for bar, feature in zip(dataset.bars, features, strict=True):
        if feature["symbol"] != bar.symbol or feature["session"] != bar.session.isoformat():
            raise ValueError("Feature row identity does not match input snapshot")
        prefix_available_at = max(prefix_available_at, bar.available_at)
        writer.writerow(
            {
                **feature,
                "snapshot_id": dataset.snapshot_id,
                "available_at": _utc(bar.available_at),
                "retrieved_at": _utc(bar.retrieved_at),
                "feature_available_at": _utc(prefix_available_at),
                "quality_status": bar.quality_status,
            }
        )
    return stream.getvalue().encode("utf-8")


def _verify_existing(directory: Path, expected: dict[str, bytes]) -> None:
    if directory.is_symlink() or not directory.is_dir():
        raise FileExistsError(f"Artifact destination is not a regular directory: {directory}")
    entries = {path.name: path for path in directory.iterdir()}
    if entries.keys() != expected.keys():
        raise FileExistsError(
            f"Existing artifact set is incomplete or contains extra files: {directory}"
        )
    for name, content in expected.items():
        path = entries[name]
        if path.is_symlink() or not path.is_file() or path.read_bytes() != content:
            raise FileExistsError(f"Existing artifact differs; refusing overwrite: {path}")


def generate_artifacts(
    dataset: OHLCVDataset,
    output_root: str | Path,
    *,
    run_at: datetime,
    config: IndicatorConfig | None = None,
    raw_input: bytes | None = None,
) -> ArtifactRun:
    """Publish a content-addressed run; an identical verified rerun safely reuses it.

    A mkdir lock serializes cooperating writers. Existing/stale locks fail closed and
    require investigation. Rename publishes the complete directory atomically; this
    provides atomic visibility, not guaranteed durability across a machine crash.
    """
    require_valid_dataset(dataset)
    if not isinstance(run_at, datetime) or run_at.tzinfo is None or run_at.utcoffset() is None:
        raise ValueError("run_at must be a timezone-aware datetime")
    if any(max(bar.available_at, bar.retrieved_at) > run_at for bar in dataset.bars):
        raise ValueError("run_at cannot precede input availability or retrieval")
    if raw_input is not None and not isinstance(raw_input, bytes):
        raise TypeError("raw_input must be bytes")
    if config is not None and not isinstance(config, IndicatorConfig):
        raise TypeError("config must be an IndicatorConfig")
    config = config if config is not None else IndicatorConfig()
    config_dict = config.to_dict()
    snapshot = canonical_json(dataset.to_dict())
    metadata = {
        "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
        "model_version": __version__,
        **feature_metadata(config),
        "serialization": {
            "encoding": "UTF-8",
            "csv_null": "empty field (warm-up or undefined denominator)",
            "csv_float": "Python float round-trip representation",
            "snapshot_hash": "SHA-256 of canonical JSON; explicit source timezone offsets preserved",
        },
        "provenance": {
            "input_snapshot": "input_snapshot.json",
            "feature_available_at": (
                "Conservative maximum source available_at through the current session; "
                "recursive indicators can depend on the complete prefix. This is source "
                "information availability, not a claim of historical execution."
            ),
            "retrieved_at": "Timestamp at which this source observation was retrieved",
        },
    }
    outputs = {
        "features.csv": _feature_csv(dataset, compute_features(dataset, config)),
        "feature_metadata.json": canonical_json(metadata),
        "data_quality.json": canonical_json(validate_dataset(dataset).to_dict()),
        "input_snapshot.json": snapshot,
    }
    manifest_body = {
        "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
        "model_version": __version__,
        "run_at": _utc(run_at),
        "configuration": config_dict,
        "configuration_sha256": sha256(canonical_json(config_dict)),
        "input": {
            "snapshot_id": dataset.snapshot_id,
            "normalized_sha256": sha256(snapshot),
            "raw_sha256": sha256(raw_input) if raw_input is not None else None,
            "bar_count": len(dataset.bars),
            "symbol": dataset.bars[0].symbol,
            "provider": dataset.bars[0].provider,
            "adjustment_policy": dataset.bars[0].adjustment_policy,
            "first_session": dataset.bars[0].session.isoformat(),
            "last_session": dataset.bars[-1].session.isoformat(),
            "latest_available_at": _utc(max(bar.available_at for bar in dataset.bars)),
            "latest_retrieved_at": _utc(max(bar.retrieved_at for bar in dataset.bars)),
        },
        "outputs": {
            name: {"sha256": sha256(content), "bytes": len(content)}
            for name, content in sorted(outputs.items())
        },
        "run_id_convention": "SHA-256 of canonical manifest excluding run_id; manifest excludes self-hash",
    }
    run_id = sha256(canonical_json(manifest_body))
    manifest = {**manifest_body, "run_id": run_id}
    outputs["manifest.json"] = canonical_json(manifest)

    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    lock = root / ".artifact-write.lock"
    try:
        lock.mkdir()
    except FileExistsError as exc:
        raise FileExistsError(
            f"Artifact writer lock exists; investigate before retrying: {lock}"
        ) from exc
    stage: Path | None = None
    try:
        destination = root / f"run-{run_id}"
        if destination.exists() or destination.is_symlink():
            _verify_existing(destination, outputs)
            return ArtifactRun(destination, run_id, manifest)
        stage = Path(tempfile.mkdtemp(prefix=".staging-", dir=root))
        for name, content in outputs.items():
            (stage / name).write_bytes(content)
        os.rename(stage, destination)
        stage = None
        return ArtifactRun(destination, run_id, manifest)
    finally:
        if stage is not None:
            shutil.rmtree(stage)
        lock.rmdir()
