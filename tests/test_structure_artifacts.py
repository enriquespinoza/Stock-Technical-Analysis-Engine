"""TAE-002E content identity, provenance, and publication safety tests."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from technical_engine.artifacts import canonical_json, generate_artifacts, sha256
from technical_engine.data import OHLCVBar, OHLCVDataset
from technical_engine.structure import SwingConfig
from technical_engine.structure_artifacts import (
    StructureArtifactConfig,
    generate_structure_artifacts,
)


@pytest.fixture
def dataset():
    highs = [12, 20, 16, 21, 22, 22, 22]
    lows = [8, 15, 11, 16, 19, 19.8, 17]
    closes = [10, 18, 14, 19, 21, 20.5, 18]
    bars = tuple(
        OHLCVBar(
            symbol="TEST",
            session=date(2024, 1, 1) + timedelta(days=i),
            open=close,
            high=high,
            low=low,
            close=close,
            volume=1000,
            provider="fixture",
            retrieved_at=datetime(2025, 1, 1, tzinfo=UTC),
            available_at=datetime(2024, 1, 1, 22, tzinfo=UTC) + timedelta(days=i),
            adjustment_policy="unadjusted",
            snapshot_id="structure-artifact-fixture",
        )
        for i, (high, low, close) in enumerate(zip(highs, lows, closes, strict=True))
    )
    return OHLCVDataset(bars, "structure-artifact-fixture")


@pytest.fixture
def config():
    return StructureArtifactConfig(swing=SwingConfig(1, 1))


@pytest.fixture
def run_at():
    return datetime(2025, 1, 2, tzinfo=UTC)


def test_four_streams_content_hashes_and_manifest(dataset, config, run_at, tmp_path):
    run = generate_structure_artifacts(dataset, tmp_path, run_at=run_at, config=config)
    files = {p.name: p.read_bytes() for p in run.directory.iterdir()}
    assert set(files) == {
        "confirmed_swings.json", "level_events.json", "trend_events.json",
        "setup_events.json", "input_snapshot.json", "manifest.json",
    }
    manifest = json.loads(files["manifest.json"])
    body = {key: value for key, value in manifest.items() if key != "run_id"}
    assert run.run_id == sha256(canonical_json(body))
    assert manifest["artifact_schema_version"] == "1.0.0"
    assert manifest["artifact_family"] == "TAE-002-market-structure"
    assert manifest["input"]["normalized_sha256"] == sha256(files["input_snapshot.json"])
    assert manifest["configuration_sha256"] == sha256(canonical_json(manifest["configuration"]))
    for name, info in manifest["outputs"].items():
        assert info == {"sha256": sha256(files[name]), "bytes": len(files[name])}
    assert manifest["record_counts"]["confirmed_swings.json"] > 0
    assert manifest["record_counts"]["setup_events.json"] > 0
    setups = json.loads(files["setup_events.json"])
    assert [event["kind"] for event in setups if event["direction"] == "UP"] == [
        "BREAKOUT", "RETEST", "FAILED_BREAKOUT"
    ]
    assert all(event["usable_at"] == "2025-01-01T00:00:00+00:00" for event in setups)


def test_identical_rerun_and_independent_root_have_identical_bytes(
    dataset, config, run_at, tmp_path
):
    first = generate_structure_artifacts(dataset, tmp_path, run_at=run_at, config=config)
    snapshot = {p.name: p.read_bytes() for p in first.directory.iterdir()}
    again = generate_structure_artifacts(dataset, tmp_path, run_at=run_at, config=config)
    other = generate_structure_artifacts(dataset, tmp_path / "other", run_at=run_at, config=config)
    assert first == again
    assert first.run_id == other.run_id
    assert snapshot == {p.name: p.read_bytes() for p in other.directory.iterdir()}


@pytest.mark.parametrize("damage", ["changed", "missing", "extra", "symlink", "directory"])
def test_corrupted_or_partial_run_never_overwritten(dataset, config, run_at, tmp_path, damage):
    run = generate_structure_artifacts(dataset, tmp_path, run_at=run_at, config=config)
    victim = run.directory / "trend_events.json"
    if damage == "changed":
        victim.write_bytes(b"tampered")
    elif damage == "missing":
        victim.unlink()
    elif damage == "extra":
        (run.directory / "unexpected").write_bytes(b"extra")
    elif damage == "symlink":
        victim.unlink()
        target = tmp_path / "victim-target"
        target.write_bytes(b"unrelated")
        try:
            victim.symlink_to(target)
        except OSError as exc:
            if getattr(exc, "winerror", None) == 1314:
                pytest.skip("Windows lacks permission to create symbolic links")
            raise
    else:
        victim.unlink()
        victim.mkdir()
    with pytest.raises(FileExistsError):
        generate_structure_artifacts(dataset, tmp_path, run_at=run_at, config=config)
    assert not (tmp_path / ".structure-artifact-write.lock").exists()


def test_lock_preserved_and_failed_publication_cleans_owned_stage(
    dataset, config, run_at, tmp_path, monkeypatch
):
    lock = tmp_path / ".structure-artifact-write.lock"
    lock.mkdir()
    (lock / "owner").write_text("foreign process")
    with pytest.raises(FileExistsError):
        generate_structure_artifacts(dataset, tmp_path, run_at=run_at, config=config)
    assert (lock / "owner").read_text() == "foreign process"
    lock.rename(tmp_path / "saved-lock")

    def fail_rename(source, destination):
        raise OSError("failed to publish")

    monkeypatch.setattr("technical_engine.structure_artifacts.os.rename", fail_rename)
    with pytest.raises(OSError, match="failed to publish"):
        generate_structure_artifacts(dataset, tmp_path, run_at=run_at, config=config)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["saved-lock"]


def test_reject_bad_run_timestamps_and_config(dataset, config, run_at, tmp_path):
    for stamp in (datetime(2025, 1, 2), "2025-01-02", None):
        with pytest.raises(ValueError, match="timezone-aware"):
            generate_structure_artifacts(dataset, tmp_path, run_at=stamp, config=config)
    with pytest.raises(ValueError, match="cannot precede"):
        generate_structure_artifacts(
            dataset, tmp_path, run_at=datetime(2024, 6, 1, tzinfo=UTC), config=config
        )
    with pytest.raises(TypeError, match="config"):
        generate_structure_artifacts(dataset, tmp_path, run_at=run_at, config={})
    for kwargs in (
        {"levels_merge_tolerance_bps": -1},
        {"trend_comparison_tolerance_bps": float("nan")},
        {"max_followup_bars": 0},
        {"breakout_buffer_bps": 10000},
        {"swing": object()},
    ):
        with pytest.raises((ValueError, TypeError)):
            StructureArtifactConfig(**kwargs)
    assert list(tmp_path.iterdir()) == []


def test_config_input_and_clock_changes_produce_distinct_identity(
    dataset, config, run_at, tmp_path
):
    baseline = generate_structure_artifacts(dataset, tmp_path, run_at=run_at, config=config)
    changed_config = generate_structure_artifacts(
        dataset, tmp_path, run_at=run_at, config=replace(config, breakout_buffer_bps=15)
    )
    changed_clock = generate_structure_artifacts(
        dataset, tmp_path, run_at=run_at + timedelta(seconds=1), config=config
    )
    changed_input = replace(dataset, bars=(*dataset.bars[:-1], replace(dataset.bars[-1], volume=21)))
    changed_data = generate_structure_artifacts(
        changed_input, tmp_path, run_at=run_at, config=config
    )
    assert len({r.run_id for r in (baseline, changed_config, changed_clock, changed_data)}) == 4
    alternate = run_at.astimezone(timezone(timedelta(hours=-5)))
    assert generate_structure_artifacts(dataset, tmp_path, run_at=alternate, config=config) == baseline


def test_existing_tae_001_artifacts_remain_unchanged(dataset, config, run_at, tmp_path):
    original = generate_artifacts(dataset, tmp_path, run_at=run_at)
    before = {p.name: p.read_bytes() for p in original.directory.iterdir()}
    structure = generate_structure_artifacts(dataset, tmp_path, run_at=run_at, config=config)
    assert structure.directory != original.directory
    assert structure.directory.name.startswith("structure-run-")
    assert {p.name: p.read_bytes() for p in original.directory.iterdir()} == before
    assert generate_artifacts(dataset, tmp_path, run_at=run_at) == original


def test_invalid_data_never_publishes(dataset, config, run_at, tmp_path):
    invalid = replace(dataset, bars=(replace(dataset.bars[0], low=30), *dataset.bars[1:]))
    with pytest.raises(ValueError):
        generate_structure_artifacts(invalid, tmp_path, run_at=run_at, config=config)
    assert not list(tmp_path.iterdir())
