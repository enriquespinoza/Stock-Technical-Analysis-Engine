"""Acceptance checks for read-only TAE-002F artifact validation."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta

import pytest

from technical_engine.artifacts import canonical_json, sha256
from technical_engine.data import OHLCVBar, OHLCVDataset
from technical_engine.structure import SwingConfig
from technical_engine.structure_artifacts import (
    StructureArtifactConfig,
    generate_structure_artifacts,
)
from technical_engine.structure_validation import validate_structure_run


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
            snapshot_id="validation-fixture",
        )
        for i, (high, low, close) in enumerate(zip(highs, lows, closes, strict=True))
    )
    return OHLCVDataset(bars, "validation-fixture")


@pytest.fixture
def published(dataset, tmp_path):
    return generate_structure_artifacts(
        dataset,
        tmp_path,
        run_at=datetime(2025, 1, 2, tzinfo=UTC),
        config=StructureArtifactConfig(swing=SwingConfig(1, 1)),
    )


def test_valid_run_checks_complete_evidence_without_mutating(published):
    before = {file.name: file.read_bytes() for file in published.directory.iterdir()}
    report = validate_structure_run(published.directory)
    assert report.run_id == published.run_id
    assert report.snapshot_id == "validation-fixture"
    assert report.integrity_verified
    assert report.deterministic_replay_verified
    assert report.exhaustive_prefix_invariance_verified
    assert report.prefix_checks == 7 * 4
    assert report.delayed_knowledge_events > 0
    assert report.research_acceptance == "NOT_ESTABLISHED"
    assert before == {file.name: file.read_bytes() for file in published.directory.iterdir()}
    with pytest.raises(FrozenInstanceError):
        report.run_id = "changed"


@pytest.mark.parametrize("filename", ["manifest.json", "input_snapshot.json", "setup_events.json"])
def test_modified_file_rejected_without_mutation(published, filename):
    target = published.directory / filename
    target.write_bytes(target.read_bytes() + b" ")
    before = target.read_bytes()
    with pytest.raises(ValueError):
        validate_structure_run(published.directory)
    assert target.read_bytes() == before


def test_manifest_rehash_cannot_hide_modified_ledger(published):
    target = published.directory / "trend_events.json"
    original = json.loads(target.read_bytes())
    original[0]["state"] = "FORGED"
    altered = canonical_json(original)
    target.write_bytes(altered)
    manifest_file = published.directory / "manifest.json"
    manifest = json.loads(manifest_file.read_bytes())
    manifest["outputs"]["trend_events.json"] = {"sha256": sha256(altered), "bytes": len(altered)}
    body = {key: value for key, value in manifest.items() if key != "run_id"}
    manifest["run_id"] = sha256(canonical_json(body))
    manifest_file.write_bytes(canonical_json(manifest))
    with pytest.raises(ValueError):
        validate_structure_run(published.directory)


def test_missing_or_extra_files_rejected(published):
    path = published.directory / "confirmed_swings.json"
    path.unlink()
    with pytest.raises(ValueError, match="missing or unexpected"):
        validate_structure_run(published.directory)
    path.write_bytes(b"[]\n")
    (published.directory / "extra.txt").write_text("unrelated")
    with pytest.raises(ValueError, match="missing or unexpected"):
        validate_structure_run(published.directory)


def test_wrong_directory_and_symlink_rejected(published, tmp_path):
    with pytest.raises(ValueError, match="missing or unexpected files"):
        validate_structure_run(published.directory.parent)
    alias = tmp_path.parent / "unsafe-alias"
    try:
        alias.symlink_to(published.directory, target_is_directory=True)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows lacks permission to create symbolic links")
        raise
    try:
        with pytest.raises(ValueError, match="regular directory"):
            validate_structure_run(alias)
    finally:
        alias.unlink()


def test_backdated_manifest_rejected_even_after_rehash(published):
    manifest_file = published.directory / "manifest.json"
    manifest = json.loads(manifest_file.read_bytes())
    manifest["run_at"] = "2024-01-01T00:00:00+00:00"
    body = {key: value for key, value in manifest.items() if key != "run_id"}
    manifest["run_id"] = sha256(canonical_json(body))
    manifest_file.write_bytes(canonical_json(manifest))
    with pytest.raises(ValueError):
        validate_structure_run(published.directory)


def test_input_mutation_changes_run_identity(dataset, tmp_path):
    changed = replace(dataset, bars=(*dataset.bars[:-1], replace(dataset.bars[-1], volume=1)))
    config = StructureArtifactConfig(swing=SwingConfig(1, 1))
    first = generate_structure_artifacts(
        dataset, tmp_path, run_at=datetime(2025, 1, 2, tzinfo=UTC), config=config
    )
    second = generate_structure_artifacts(
        changed, tmp_path, run_at=datetime(2025, 1, 2, tzinfo=UTC), config=config
    )
    assert first.run_id != second.run_id
    assert validate_structure_run(first.directory).snapshot_id == dataset.snapshot_id
    assert validate_structure_run(second.directory).run_id == second.run_id
