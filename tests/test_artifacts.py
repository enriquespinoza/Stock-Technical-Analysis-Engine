"""Artifact integrity, provenance, reproducibility and publication safety."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from technical_engine.artifacts import canonical_json, generate_artifacts, sha256
from technical_engine.data import OHLCVBar, OHLCVDataset
from technical_engine.indicators import IndicatorConfig


@pytest.fixture
def dataset() -> OHLCVDataset:
    bars = tuple(
        OHLCVBar(
            symbol="TEST",
            session=date(2024, 1, 1) + timedelta(days=i),
            open=100.0 + i,
            high=102.0 + i,
            low=99.0 + i,
            close=101.0 + i,
            volume=1000.0 + i,
            provider="fixture",
            retrieved_at=datetime(2025, 1, 1, tzinfo=UTC),
            available_at=datetime(2024, 1, 1, 22, tzinfo=UTC) + timedelta(days=i),
            adjustment_policy="unadjusted",
            snapshot_id="test-snapshot-v1",
        )
        for i in range(40)
    )
    return OHLCVDataset(bars=bars, snapshot_id="test-snapshot-v1")


@pytest.fixture
def run_at() -> datetime:
    return datetime(2025, 1, 2, tzinfo=UTC)


def test_reproducible_manifest_and_output_hashes(dataset, run_at, tmp_path):
    raw = canonical_json(dataset.to_dict())
    first = generate_artifacts(dataset, tmp_path, run_at=run_at, raw_input=raw)
    before = {path.name: path.read_bytes() for path in first.directory.iterdir()}
    second = generate_artifacts(dataset, tmp_path, run_at=run_at, raw_input=raw)
    independent = generate_artifacts(dataset, tmp_path / "other", run_at=run_at, raw_input=raw)
    assert first == second
    assert before == {path.name: path.read_bytes() for path in independent.directory.iterdir()}
    manifest = json.loads(before["manifest.json"])
    assert manifest["input"]["raw_sha256"] == sha256(raw)
    assert manifest["input"]["normalized_sha256"] == sha256(before["input_snapshot.json"])
    assert manifest["configuration_sha256"] == sha256(canonical_json(manifest["configuration"]))
    assert manifest["run_id"] == first.run_id
    body = {key: value for key, value in manifest.items() if key != "run_id"}
    assert sha256(canonical_json(body)) == first.run_id
    for name, integrity in manifest["outputs"].items():
        assert integrity == {"sha256": sha256(before[name]), "bytes": len(before[name])}
    assert set(before) == {
        "features.csv",
        "feature_metadata.json",
        "data_quality.json",
        "input_snapshot.json",
        "manifest.json",
    }
    assert json.loads(before["data_quality.json"])["is_valid"] is True


def test_csv_provenance_and_warmup(dataset, run_at, tmp_path):
    run = generate_artifacts(dataset, tmp_path, run_at=run_at)
    rows = list(csv.DictReader(io.StringIO((run.directory / "features.csv").read_text())))
    assert len(rows) == 40
    assert rows[0]["symbol"] == "TEST"
    assert rows[0]["session"] == "2024-01-01"
    assert rows[0]["snapshot_id"] == dataset.snapshot_id
    assert rows[0]["sma_20"] == ""
    assert rows[19]["sma_20"] != ""
    assert rows[0]["available_at"] == "2024-01-01T22:00:00+00:00"
    assert rows[-1]["retrieved_at"] == "2025-01-01T00:00:00+00:00"
    assert rows[-1]["feature_available_at"] == dataset.bars[-1].available_at.isoformat()
    assert (
        "feature_available_at"
        in json.loads((run.directory / "feature_metadata.json").read_text())["provenance"]
    )


def test_feature_availability_uses_late_prior_information(dataset, run_at, tmp_path):
    late_bar = replace(dataset.bars[0], available_at=datetime(2024, 12, 1, tzinfo=UTC))
    late = replace(dataset, bars=(late_bar, *dataset.bars[1:]))
    run = generate_artifacts(late, tmp_path, run_at=run_at)
    rows = list(csv.DictReader(io.StringIO((run.directory / "features.csv").read_text())))
    assert rows[1]["available_at"] == dataset.bars[1].available_at.isoformat()
    assert rows[1]["feature_available_at"] == late_bar.available_at.isoformat()


@pytest.mark.parametrize("change", ["timestamp", "config", "input", "raw"])
def test_changed_run_inputs_never_overwrite(dataset, run_at, tmp_path, change):
    original = generate_artifacts(dataset, tmp_path, run_at=run_at)
    contents = {p.name: p.read_bytes() for p in original.directory.iterdir()}
    kwargs = {"run_at": run_at}
    if change == "timestamp":
        kwargs["run_at"] += timedelta(seconds=1)
    elif change == "config":
        kwargs["config"] = IndicatorConfig(sma_windows=(10,))
    elif change == "input":
        dataset = replace(dataset, bars=(replace(dataset.bars[0], volume=42.0), *dataset.bars[1:]))
    else:
        kwargs["raw_input"] = b"source input"
    changed = generate_artifacts(dataset, tmp_path, **kwargs)
    assert changed.directory != original.directory
    assert contents == {p.name: p.read_bytes() for p in original.directory.iterdir()}


@pytest.mark.parametrize("damage", ["changed", "missing", "extra", "symlink", "directory"])
def test_existing_damaged_run_is_not_overwritten(dataset, run_at, tmp_path, damage):
    run = generate_artifacts(dataset, tmp_path, run_at=run_at)
    victim = run.directory / "features.csv"
    if damage == "changed":
        victim.write_bytes(b"corruption")
    elif damage == "missing":
        victim.unlink()
    elif damage == "extra":
        (run.directory / "extra").write_text("keep")
    elif damage == "symlink":
        victim.unlink()
        target = tmp_path / "target"
        target.write_text("keep")
        victim.symlink_to(target)
    else:
        victim.unlink()
        victim.mkdir()
    with pytest.raises(FileExistsError):
        generate_artifacts(dataset, tmp_path, run_at=run_at)
    if damage == "changed":
        assert victim.read_bytes() == b"corruption"
    elif damage == "extra":
        assert (run.directory / "extra").read_text() == "keep"
    assert not (tmp_path / ".artifact-write.lock").exists()


def test_existing_writer_lock_is_preserved(dataset, run_at, tmp_path):
    lock = tmp_path / ".artifact-write.lock"
    lock.mkdir()
    (lock / "owner").write_text("another run")
    with pytest.raises(FileExistsError, match="writer lock"):
        generate_artifacts(dataset, tmp_path, run_at=run_at)
    assert (lock / "owner").read_text() == "another run"
    assert list(tmp_path.iterdir()) == [lock]


def test_failed_publication_cleans_only_own_temporary_files(dataset, run_at, tmp_path, monkeypatch):
    def fail_rename(source: Path, destination: Path) -> None:
        raise OSError("simulated publication failure")

    monkeypatch.setattr("technical_engine.artifacts.os.rename", fail_rename)
    sentinel = tmp_path / "unrelated"
    sentinel.write_text("keep")
    with pytest.raises(OSError, match="simulated"):
        generate_artifacts(dataset, tmp_path, run_at=run_at)
    assert list(tmp_path.iterdir()) == [sentinel]
    assert sentinel.read_text() == "keep"


@pytest.mark.parametrize("timestamp", [datetime(2025, 1, 2), "2025-01-02", None])
def test_missing_timezone_rejected(dataset, timestamp, tmp_path):
    with pytest.raises(ValueError, match="timezone-aware"):
        generate_artifacts(dataset, tmp_path, run_at=timestamp)
    assert not list(tmp_path.iterdir())


def test_backdated_run_rejected(dataset, tmp_path):
    with pytest.raises(ValueError, match="cannot precede"):
        generate_artifacts(dataset, tmp_path, run_at=datetime(2024, 6, 1, tzinfo=UTC))
    assert not list(tmp_path.iterdir())


def test_equivalent_run_timestamp_offsets_have_same_identity(dataset, run_at, tmp_path):
    utc_run = generate_artifacts(dataset, tmp_path, run_at=run_at)
    offset = timezone(timedelta(hours=-5))
    alternate = generate_artifacts(dataset, tmp_path, run_at=run_at.astimezone(offset))
    assert utc_run == alternate


def test_invalid_data_never_publishes(dataset, run_at, tmp_path):
    invalid = replace(dataset, bars=(replace(dataset.bars[0], close=-1.0), *dataset.bars[1:]))
    with pytest.raises(ValueError):
        generate_artifacts(invalid, tmp_path, run_at=run_at)
    assert not list(tmp_path.iterdir())


def test_serialized_snapshot_roundtrip(dataset, run_at, tmp_path):
    run = generate_artifacts(dataset, tmp_path, run_at=run_at)
    parsed = json.loads((run.directory / "input_snapshot.json").read_bytes())
    assert OHLCVDataset.from_dict(parsed) == dataset


def test_canonical_json_rejects_nonfinite_values():
    with pytest.raises(ValueError):
        canonical_json({"bad": float("nan")})


@pytest.mark.parametrize("field,value", [("config", {}), ("raw_input", "not bytes")])
def test_invalid_argument_types_do_not_publish(dataset, run_at, tmp_path, field, value):
    with pytest.raises(TypeError, match=field):
        generate_artifacts(dataset, tmp_path, run_at=run_at, **{field: value})
    assert not list(tmp_path.iterdir())


def test_default_config_file_matches_code_defaults():
    root = Path(__file__).resolve().parents[1]
    parsed = json.loads((root / "config/default.json").read_bytes())
    assert IndicatorConfig.from_dict(parsed) == IndicatorConfig()
