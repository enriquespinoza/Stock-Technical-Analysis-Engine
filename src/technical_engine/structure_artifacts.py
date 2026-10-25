"""Independent, content-addressed research exports for TAE-002A through TAE-002D.

This is deliberately separate from the frozen TAE-001 artifact contract.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from technical_engine._version import __version__
from technical_engine.artifacts import ArtifactRun, _verify_existing, canonical_json, sha256
from technical_engine.data import OHLCVDataset, require_valid_dataset
from technical_engine.levels import LevelConfig, level_events
from technical_engine.setups import SetupConfig, setup_events
from technical_engine.structure import SwingConfig, confirmed_swings
from technical_engine.trends import TrendConfig, trend_events

STRUCTURE_ARTIFACT_SCHEMA_VERSION = "1.0.0"


@dataclass(frozen=True)
class StructureArtifactConfig:
    """One coherent swing definition shared across the exported modules."""

    swing: SwingConfig = field(default_factory=SwingConfig)
    levels_merge_tolerance_bps: float = 50.0
    trend_comparison_tolerance_bps: float = 0.0
    breakout_buffer_bps: float = 0.0
    retest_tolerance_bps: float = 25.0
    max_followup_bars: int = 5

    def __post_init__(self) -> None:
        if not isinstance(self.swing, SwingConfig):
            raise TypeError("swing must be a SwingConfig")
        self.level_config()
        self.trend_config()
        self.setup_config()

    def level_config(self) -> LevelConfig:
        return LevelConfig(self.swing, self.levels_merge_tolerance_bps)

    def trend_config(self) -> TrendConfig:
        return TrendConfig(self.swing, self.trend_comparison_tolerance_bps)

    def setup_config(self) -> SetupConfig:
        return SetupConfig(
            levels=self.level_config(),
            breakout_buffer_bps=self.breakout_buffer_bps,
            retest_tolerance_bps=self.retest_tolerance_bps,
            max_followup_bars=self.max_followup_bars,
        )


def _jsonable(value: Any) -> Any:
    """Convert immutable event records into stable, strictly JSON-safe values."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value


def generate_structure_artifacts(
    dataset: OHLCVDataset,
    output_root: str | Path,
    *,
    run_at: datetime,
    config: StructureArtifactConfig | None = None,
) -> ArtifactRun:
    """Atomically publish immutable, hash-verified TAE-002 research evidence.

    An identical verified rerun returns the existing run. A mismatched existing
    run, symlink, incomplete run, or active writer lock fails closed.
    """
    require_valid_dataset(dataset)
    if not isinstance(run_at, datetime) or run_at.tzinfo is None or run_at.utcoffset() is None:
        raise ValueError("run_at must be a timezone-aware datetime")
    if any(max(bar.available_at, bar.retrieved_at) > run_at for bar in dataset.bars):
        raise ValueError("run_at cannot precede input availability or retrieval")
    if config is None:
        config = StructureArtifactConfig()
    if not isinstance(config, StructureArtifactConfig):
        raise TypeError("config must be a StructureArtifactConfig")

    config_dict = _jsonable(asdict(config))
    input_bytes = canonical_json(dataset.to_dict())
    streams = {
        "confirmed_swings.json": confirmed_swings(dataset, config.swing),
        "level_events.json": level_events(dataset, config.level_config()),
        "trend_events.json": trend_events(dataset, config.trend_config()),
        "setup_events.json": setup_events(dataset, config.setup_config()),
    }
    outputs: dict[str, bytes] = {
        filename: canonical_json(_jsonable([asdict(record) for record in records]))
        for filename, records in streams.items()
    }
    outputs["input_snapshot.json"] = input_bytes
    body: dict[str, Any] = {
        "artifact_family": "TAE-002-market-structure",
        "artifact_schema_version": STRUCTURE_ARTIFACT_SCHEMA_VERSION,
        "model_version": __version__,
        "run_at": run_at.astimezone(UTC).isoformat(),
        "configuration": config_dict,
        "configuration_sha256": sha256(canonical_json(config_dict)),
        "input": {
            "snapshot_id": dataset.snapshot_id,
            "normalized_sha256": sha256(input_bytes),
            "symbol": dataset.bars[0].symbol,
            "provider": dataset.bars[0].provider,
            "adjustment_policy": dataset.bars[0].adjustment_policy,
            "bar_count": len(dataset.bars),
            "first_session": dataset.bars[0].session.isoformat(),
            "last_session": dataset.bars[-1].session.isoformat(),
        },
        "record_counts": {name: len(records) for name, records in sorted(streams.items())},
        "outputs": {
            name: {"sha256": sha256(data), "bytes": len(data)}
            for name, data in sorted(outputs.items())
        },
        "run_id_convention": "SHA-256 of canonical manifest without run_id",
    }
    run_id = sha256(canonical_json(body))
    manifest = {**body, "run_id": run_id}
    outputs["manifest.json"] = canonical_json(manifest)

    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    lock = root / ".structure-artifact-write.lock"
    try:
        lock.mkdir()
    except FileExistsError as exc:
        raise FileExistsError(f"Structure artifact writer lock exists: {lock}") from exc
    stage: Path | None = None
    try:
        destination = root / f"structure-run-{run_id}"
        if destination.exists() or destination.is_symlink():
            _verify_existing(destination, outputs)
            return ArtifactRun(destination, run_id, manifest)
        stage = Path(tempfile.mkdtemp(prefix=".structure-staging-", dir=root))
        for name, data in outputs.items():
            (stage / name).write_bytes(data)
        os.rename(stage, destination)
        stage = None
        return ArtifactRun(destination, run_id, manifest)
    finally:
        if stage is not None:
            shutil.rmtree(stage)
        lock.rmdir()
