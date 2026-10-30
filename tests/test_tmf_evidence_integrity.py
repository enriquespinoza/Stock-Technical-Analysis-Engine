"""Synthetic-only TMF source and diagnostic-manifest byte-integrity tests."""

from __future__ import annotations

import json
from pathlib import Path
from runpy import run_path

import pytest

from technical_engine.artifacts import canonical_json, sha256

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "audit_tmf_evidence.py"


def functions():
    return run_path(str(SCRIPT))


def test_reported_hash_match_mismatch_and_missing(tmp_path):
    verify = functions()["verify_sources"]
    content = b"synthetic example\r\n"
    name = "StrategyReports_TMF_HIGHS.csv"
    (tmp_path / name).write_bytes(content)
    expected = {name: sha256(content)}
    assert verify(tmp_path, expected)[name]["status"] == "MATCH"
    (tmp_path / name).write_bytes(content + b"\n")
    assert verify(tmp_path, expected)[name]["status"] == "MISMATCH"
    (tmp_path / name).unlink()
    assert verify(tmp_path, expected)[name]["status"] == "MISSING"


def test_run_manifest_integrity_and_mutation(tmp_path):
    verify = functions()["verify_run"]
    sources = {
        "snapshot_raw_sha256": ("input_snapshot.json", b"snapshot"),
        "high_report_sha256": ("StrategyReports_TMF_HIGHS.csv", b"high"),
        "low_report_sha256": ("StrategyReports_TMF_LOWS.csv", b"low"),
        "study_source_sha256": ("study.ts", b"study"),
        "exporter_source_sha256": ("exporter.ts", b"export"),
    }
    for filename, content in sources.values():
        (tmp_path / filename).write_bytes(content)
    inputs = {key: sha256(content) for key, (_, content) in sources.items()}
    run_id = sha256(canonical_json({"contract": "tae-tos-001-v2", **inputs}))
    run = tmp_path / f"run-{run_id}"
    run.mkdir()
    capture = b"synthetic capture only"
    (run / "tos_swing_capture.csv").write_bytes(capture)
    manifest = {
        "contract": "tae-tos-001-v2",
        "inputs": inputs,
        "capture_csv_sha256": sha256(capture),
        "verification_warnings": [],
        "platform_execution_verified": False,
        "research_acceptance": "NOT_ESTABLISHED",
    }
    (run / "diagnostic_manifest.json").write_bytes(canonical_json(manifest))
    study = tmp_path / "study.ts"
    exporter = tmp_path / "exporter.ts"
    assert verify(tmp_path, run, study, exporter)["status"] == "CONSISTENT"
    exporter.write_bytes(b"export changed")
    changed = verify(tmp_path, run, study, exporter)
    assert changed["status"] == "INCONSISTENT"
    assert "exporter_source_sha256" in changed["failures"]
    exporter.write_bytes(b"export")
    (run / "tos_swing_capture.csv").write_bytes(b"tampered")
    assert "CAPTURE_CSV_SHA256" in verify(tmp_path, run, study, exporter)["failures"]
    (run / "tos_swing_capture.csv").write_bytes(capture)
    (run / "diagnostic_manifest.json").write_bytes(
        canonical_json({**manifest, "platform_execution_verified": True})
    )
    assert "PLATFORM_EXECUTION_STATUS" in verify(tmp_path, run, study, exporter)["failures"]


def test_invalid_manifest_rejected(tmp_path):
    verify = functions()["verify_run"]
    run = tmp_path / "run-invalid"
    run.mkdir()
    (run / "tos_swing_capture.csv").write_bytes(b"synthetic")
    (run / "diagnostic_manifest.json").write_text(
        json.dumps({"contract": "tae-tos-001-v2", "inputs": {}}), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="manifest input keys"):
        verify(tmp_path, run, tmp_path / "study.ts", tmp_path / "exporter.ts")


def test_refuse_filename_traversal_and_invalid_digest(tmp_path):
    verify = functions()["verify_sources"]
    with pytest.raises(ValueError, match="basenames"):
        verify(tmp_path, {"../outside": "a" * 64})
    with pytest.raises(ValueError, match="canonical SHA-256"):
        verify(tmp_path, {"ordinary.csv": "bad"})
