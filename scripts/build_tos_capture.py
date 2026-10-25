"""Reprocess thinkorswim swing reports into a new immutable diagnostic evidence run."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from technical_engine.artifacts import canonical_json, sha256
from technical_engine.data import OHLCVDataset
from technical_engine.structure import SwingConfig
from technical_engine.tos_parity import (
    ParityDifference,
    SwingObservation,
    ThinkScriptCapture,
    compare_swing_capture,
)
from technical_engine.tos_report import merged_capture_csv, parse_swing_strategy_report


def _save_run(root: Path, run_id: str, files: dict[str, bytes]) -> Path:
    """Publish a run without overwriting previous evidence."""
    root.mkdir(parents=True, exist_ok=True)
    dest = root / f"run-{run_id}"
    if dest.exists() or dest.is_symlink():
        if dest.is_symlink() or not dest.is_dir():
            raise FileExistsError(f"Destination is not a regular directory: {dest}")
        if {path.name for path in dest.iterdir()} != set(files):
            raise FileExistsError(f"Existing evidence has missing/extra files: {dest}")
        for name, data in files.items():
            path = dest / name
            if path.is_symlink() or not path.is_file() or path.read_bytes() != data:
                raise FileExistsError(f"Existing evidence differs; refusing overwrite: {path}")
        return dest
    stage = Path(tempfile.mkdtemp(prefix=".tae-tos-staging-", dir=root))
    try:
        for name, data in files.items():
            (stage / name).write_bytes(data)
        os.rename(stage, dest)
        return dest
    finally:
        if stage.exists():
            shutil.rmtree(stage)



def _difference_json(item: ParityDifference) -> dict[str, object]:
    """Return canonical-JSON-safe diagnostics including ISO session dates."""

    def observation(value: SwingObservation | None) -> dict[str, object] | None:
        if value is None:
            return None
        result = asdict(value)
        result["pivot_session"] = value.pivot_session.isoformat()
        result["confirmation_session"] = value.confirmation_session.isoformat()
        return result

    return {
        "kind": item.kind,
        "key": list(item.key),
        "expected": observation(item.expected),
        "observed": observation(item.observed),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail-closed TOS report parity diagnostics")
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--high-report", required=True, type=Path)
    parser.add_argument("--low-report", required=True, type=Path)
    parser.add_argument("--study", required=True, type=Path)
    parser.add_argument("--exporter", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--high-export-highs", required=True, choices=("yes", "no"))
    parser.add_argument("--low-export-highs", required=True, choices=("yes", "no"))
    args = parser.parse_args(argv)
    if args.high_export_highs != "yes" or args.low_export_highs != "no":
        parser.error("HIGH pass needs exportHighs=yes; LOW pass exportHighs=no")

    snapshot_raw = args.snapshot.read_bytes()
    dataset = OHLCVDataset.from_dict(json.loads(snapshot_raw))
    symbol = dataset.bars[0].symbol
    sessions = tuple(bar.session.isoformat() for bar in dataset.bars)
    high_raw = args.high_report.read_bytes()
    low_raw = args.low_report.read_bytes()
    study_raw = args.study.read_bytes()
    exporter_raw = args.exporter.read_bytes()
    high = parse_swing_strategy_report(
        high_raw,
        symbol=symbol,
        expected_kind="HIGH",
        sessions=sessions,
        pivot_prices=tuple(bar.high for bar in dataset.bars),
        right_bars=2,
    )
    low = parse_swing_strategy_report(
        low_raw,
        symbol=symbol,
        expected_kind="LOW",
        sessions=sessions,
        pivot_prices=tuple(bar.low for bar in dataset.bars),
        right_bars=2,
    )
    capture_csv = merged_capture_csv(high, low)
    capture = ThinkScriptCapture(
        symbol=symbol,
        aggregation="DAY",
        snapshot_sha256=sha256(canonical_json(dataset.to_dict())),
        study_sha256=sha256(study_raw),
        # Processing time only. Not a platform-attested capture timestamp.
        captured_at=datetime.now(UTC),
        bar_count=len(dataset.bars),
        first_session=dataset.bars[0].session,
        last_session=dataset.bars[-1].session,
    )
    result = compare_swing_capture(
        dataset,
        SwingConfig(left=2, right=2, tolerance_bps=0.0),
        capture_csv,
        capture=capture,
        study_source=study_raw,
    )
    input_hashes = {
        "snapshot_raw_sha256": sha256(snapshot_raw),
        "high_report_sha256": high.report_sha256,
        "low_report_sha256": low.report_sha256,
        "study_source_sha256": sha256(study_raw),
        "exporter_source_sha256": sha256(exporter_raw),
    }
    run_id = sha256(canonical_json({"contract": "tae-tos-001-v2", **input_hashes}))
    warnings = (*high.warnings, *low.warnings)
    metadata = {
        "contract": "tae-tos-001-v2",
        "symbol": symbol,
        "aggregation": "DAY",
        "first_session": sessions[0],
        "last_session": sessions[-1],
        "bar_count": len(sessions),
        "settings_operator_asserted": {
            "high_pass_exportHighs": args.high_export_highs,
            "low_pass_exportHighs": args.low_export_highs,
        },
        "config": {"left": 2, "right": 2, "tolerance_bps": 0.0},
        "inputs": input_hashes,
        "capture_csv_sha256": sha256(capture_csv.encode("utf-8")),
        "high_events": len(high.events),
        "low_events": len(low.events),
        "verification_warnings": list(warnings),
        "diagnostic_comparison": {
            "python_count": result.python_count,
            "captured_count": result.captured_count,
            "matched_count": result.matched_count,
            "comparison_complete": result.comparison_complete,
            "differences": [_difference_json(item) for item in result.differences],
        },
        "platform_execution_verified": False,
        "captured_at_platform_attested": None,
        "last_bar_next_order_limitation": True,
        "research_acceptance": "NOT_ESTABLISHED",
    }
    files = {
        "tos_swing_capture.csv": capture_csv.encode("utf-8"),
        "diagnostic_manifest.json": canonical_json(metadata),
    }
    directory = _save_run(args.output_root, run_id, files)
    print("Output:", directory)
    print("Python events:", result.python_count)
    print("TOS events:", result.captured_count)
    print("Matched:", result.matched_count)
    print("Differences:", len(result.differences))
    print("Verification warnings:", len(warnings))
    print("Comparison complete:", result.comparison_complete)
    print("Research acceptance: NOT_ESTABLISHED")
    return 0 if result.comparison_complete and not warnings else 1


if __name__ == "__main__":
    raise SystemExit(main())
