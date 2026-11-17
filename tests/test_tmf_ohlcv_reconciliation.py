"""Synthetic-only independent-reference reconciliation tests (no vendor data)."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from runpy import run_path

import pytest

from technical_engine.artifacts import sha256

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "reconcile_tmf_ohlcv.py"
MODULE = run_path(str(SCRIPT))
RECONCILE = MODULE["reconcile"]
SAVE = MODULE["save_local_run"]


def synthetic_capture(tmp_path: Path) -> tuple[Path, str]:
    """Create 3 deliberately nonmarket dates in a fake original TOS report."""
    root = tmp_path / "tmf"
    ref = root / "reference" / "tiingo"
    ref.mkdir(parents=True)
    values = [
        ("2026-01-01", "10", "11", "9", "10.5", "1000.25"),
        ("2026-01-02", "10", "11", "9", "10.5", "1200.75"),
        ("2026-01-03", "10", "11", "9", "10.5", "1000"),
    ]
    header = "Id;Strategy;Side;Amount;Price;Date/Time;Trade P/L;P/L;Position;"
    lines = ["Strategy report", "Symbol: TMF", "Generated: synthetic", "x", "y", header]
    for index, (session, op, hi, lo, cl, vol) in enumerate(values, 1):
        mmddyy = f"{session[5:7]}/{session[8:10]}/{session[2:4]}"
        label = f"TAE_TMF_OHLCV_Export(OHLCV|TMF|{op}|{hi}|{lo}|{cl}|{vol})"
        lines.append(f"{2 * index - 1};{label};Buy to Open;1;1;{mmddyy};0;0;0;")
        lines.append(
            f"{2 * index};TAE_TMF_OHLCV_Export(ExportExit);Sell to Close;1;1;{mmddyy};0;0;0;"
        )
    report = ("\r\n".join(lines) + "\r\n").encode("utf-8")
    (root / "StrategyReports_TMF_OHLCV.csv").write_bytes(report)

    csv_stream = io.StringIO(newline="")
    writer = csv.writer(csv_stream, lineterminator="\n")
    writer.writerow(["session", "open", "high", "low", "close", "volume"])
    writer.writerows(values)
    (root / "tmf_daily_ohlcv.csv").write_text(csv_stream.getvalue(), encoding="utf-8")
    snapshot = {
        "bars": [
            {
                "session": row[0],
                "symbol": "TMF",
                **dict(zip(("open", "high", "low", "close", "volume"), row[1:], strict=True)),
            }
            for row in values
        ]
    }
    snapshot_bytes = json.dumps(snapshot).encode("utf-8")
    (root / "input_snapshot.json").write_bytes(snapshot_bytes)
    (root / "source_metadata.json").write_text(
        json.dumps(
            {
                "source_sha256": sha256(report),
                "snapshot_sha256": sha256(snapshot_bytes),
                "adjustment_policy": "unverified_chart_adjustments",
                "captured_at": "2026-10-25T14:27:50+00:00",
            }
        ),
        encoding="utf-8",
    )

    vendor = []
    for index, (session, _op, _hi, _lo, _cl, _vol) in enumerate(values):
        vendor.append(
            {
                "date": f"{session}T00:00:00.000Z",
                "open": "10",
                "high": "11",
                "low": "9.005" if index == 1 else "9",
                "close": "10.5",
                "volume": 1000,
                "adjOpen": "9",
                "adjHigh": "10",
                "adjLow": "8",
                "adjClose": "9.5",
                "adjVolume": 1000,
                "divCash": "0",
                "splitFactor": "1",
            }
        )
    response = json.dumps(vendor).encode("utf-8")
    (ref / "tmf_eod_original.json").write_bytes(response)
    (ref / "manifest.json").write_text(
        json.dumps(
            {
                "ticker": "TMF",
                "bar_count": 3,
                "requested_start": "2026-01-01",
                "requested_end": "2026-01-03",
                "sha256": sha256(response),
                "http_status": 200,
                "content_type": "application/json",
                "retrieved_at_utc": "2026-10-30T12:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    return root, sha256(report)


def check(root: Path, digest: str):
    return RECONCILE(
        root,
        expected_source_sha256=digest,
        expected_count=3,
        first_session="2026-01-01",
        last_session="2026-01-03",
    )


def test_reconcile_raw_source_and_independent_reference(tmp_path):
    root, digest = synthetic_capture(tmp_path)
    summary, ledger = check(root, digest)
    assert summary["raw_ohlc_exact_matches"] == {"open": 3, "high": 3, "low": 2, "close": 3}
    assert summary["raw_ohlc_exact_total"] == 11
    assert summary["adjusted_ohlc_exact_matches"] == dict.fromkeys(
        ("open", "high", "low", "close"), 0
    )
    assert summary["adjusted_volume_exact_matches"] == 1
    assert summary["price_discrepancy_sessions"] == ["2026-01-02"]
    assert summary["volume_categories"] == {
        "positive_subshare": 1,
        "positive_material": 1,
        "exact": 1,
    }
    assert summary["fractional_local_volume_count"] == 2
    assert summary["rounding_matches_among_volume_mismatches"] == 1
    assert summary["truncation_matches_among_volume_mismatches"] == 1
    assert summary["material_volume_sessions"] == ["2026-01-02"]
    assert len(ledger) == 3
    assert ledger[1]["price_raw_deltas"] == {"low": "-0.005"}
    assert ledger[1]["volume_classification"] == "positive_material"
    assert summary["full_bar_equivalence_verified"] is False
    assert summary["research_acceptance"] == "NOT_ESTABLISHED"
    assert summary["recovered_exporter_candidate_status"] == "NOT_PRESENT"


def test_original_report_and_derived_csv_disagreement_fails_closed(tmp_path):
    root, digest = synthetic_capture(tmp_path)
    csv_file = root / "tmf_daily_ohlcv.csv"
    csv_file.write_text(csv_file.read_text().replace("1000.25", "1001.25"), encoding="utf-8")
    with pytest.raises(ValueError, match="Original report to normalized CSV"):
        check(root, digest)


def test_original_report_hash_mutation_fails_closed(tmp_path):
    root, digest = synthetic_capture(tmp_path)
    source = root / "StrategyReports_TMF_OHLCV.csv"
    source.write_bytes(source.read_bytes() + b"tampering")
    with pytest.raises(ValueError, match="audited fingerprint"):
        check(root, digest)


def test_tiingo_manifest_hash_mutation_fails_closed(tmp_path):
    root, digest = synthetic_capture(tmp_path)
    reference = root / "reference/tiingo/tmf_eod_original.json"
    reference.write_bytes(reference.read_bytes() + b" ")
    with pytest.raises(ValueError, match="Tiingo response hash"):
        check(root, digest)


def test_snapshot_drift_fails_closed(tmp_path):
    root, digest = synthetic_capture(tmp_path)
    snapshot = root / "input_snapshot.json"
    snapshot.write_bytes(snapshot.read_bytes() + b" ")
    with pytest.raises(ValueError, match="hashes disagree"):
        check(root, digest)


def test_duplicate_reference_session_fails_closed(tmp_path):
    root, digest = synthetic_capture(tmp_path)
    reference = root / "reference/tiingo/tmf_eod_original.json"
    bars = json.loads(reference.read_bytes())
    bars[1]["date"] = bars[0]["date"]
    raw = json.dumps(bars).encode("utf-8")
    reference.write_bytes(raw)
    manifest = root / "reference/tiingo/manifest.json"
    data = json.loads(manifest.read_bytes())
    data["sha256"] = sha256(raw)
    manifest.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="Tiingo must contain"):
        check(root, digest)


def test_unqualified_reference_manifest_fails_closed(tmp_path):
    root, digest = synthetic_capture(tmp_path)
    manifest = root / "reference/tiingo/manifest.json"
    data = json.loads(manifest.read_bytes())
    data["retrieved_at_utc"] = "2026-10-30T12:00:00-04:00"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="must be in UTC"):
        check(root, digest)


def test_invalid_reference_ohlc_relationship_fails_closed(tmp_path):
    root, digest = synthetic_capture(tmp_path)
    reference = root / "reference/tiingo/tmf_eod_original.json"
    bars = json.loads(reference.read_bytes())
    bars[0]["high"] = "9"
    raw = json.dumps(bars).encode("utf-8")
    reference.write_bytes(raw)
    manifest = root / "reference/tiingo/manifest.json"
    data = json.loads(manifest.read_bytes())
    data["sha256"] = sha256(raw)
    manifest.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="Inconsistent OHLC"):
        check(root, digest)


def test_wrong_recovered_exporter_fingerprint_fails_closed(tmp_path):
    root, digest = synthetic_capture(tmp_path)
    candidate = root / "platform_sources/TAE_TMF_OHLCV_Export.ts"
    candidate.parent.mkdir()
    candidate.write_text("# Not the recorded exporter candidate", encoding="utf-8")
    with pytest.raises(ValueError, match="Recovered exporter differs"):
        check(root, digest)


def test_local_immutable_output_idempotent_and_tamper_rejected(tmp_path):
    root, digest = synthetic_capture(tmp_path)
    summary, ledger = check(root, digest)
    output = root / "reconciliation"
    target = SAVE(output, summary, ledger)
    assert target.exists()
    assert SAVE(output, summary, ledger) == target
    assert (
        json.loads((target / "summary.json").read_bytes())["research_acceptance"]
        == "NOT_ESTABLISHED"
    )
    (target / "per_session_ledger.json").write_text("tampered", encoding="utf-8")
    with pytest.raises(FileExistsError, match="refusing overwrite"):
        SAVE(output, summary, ledger)


def test_refuses_symlinked_source(tmp_path):
    root, digest = synthetic_capture(tmp_path)
    source = root / "StrategyReports_TMF_OHLCV.csv"
    actual = root / "original.backup"
    source.rename(actual)
    try:
        source.symlink_to(actual)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation not permitted")
    with pytest.raises(ValueError, match="regular file"):
        check(root, digest)
