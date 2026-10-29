"""Read-only hash verification of locally excluded thinkorswim evidence.

Byte consistency is not source authenticity, point-in-time validation or
independent platform execution attestation. Never outputs raw market data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from technical_engine.artifacts import canonical_json, sha256

OPERATOR_HASHES = {
    "StrategyReports_TMF_OHLCV.csv": "cc0d099ab35859cb0106ff1959b7c14f97a96ed55fc3c75b314dc09f0dd3bdbe",
    "StrategyReports_TMF_HIGHS.csv": "cd32c25e336d9e5c7660b922ca2c56a9a0fe2779776e1f5400b67bfe7de5ca84",
    "StrategyReports_TMF_LOWS.csv": "e2471593958fa0b6de2b68f6a3f200aa71132caad41415c79cb838fa4240fb98",
    "input_snapshot.json": "3e66815197ee60b68489306d61dad8462cd1c25b92ec250dd72706e615add7e4",
    "tos_swing_capture_auto.csv": "64651c7fcd6d9a3ec2aa90e8b7a9192e19c113c89f35591cbe2db328e95d3655",
}


def file_hash(path: Path) -> tuple[str, int]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Not a regular file: {path}")
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1048576), b""):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def verify_sources(root: Path, expected: dict[str, str]) -> dict[str, dict[str, object]]:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Evidence root must be a regular directory")
    results = {}
    for filename, recorded in sorted(expected.items()):
        if Path(filename).name != filename or filename in ("", ".", ".."):
            raise ValueError("Evidence names must be simple basenames")
        if len(recorded) != 64 or any(char not in "0123456789abcdef" for char in recorded):
            raise ValueError("Expected digest must be canonical SHA-256")
        path = root / filename
        if not path.exists() and not path.is_symlink():
            results[filename] = {"status": "MISSING", "expected_sha256": recorded}
            continue
        observed, size = file_hash(path)
        results[filename] = {
            "status": "MATCH" if observed == recorded else "MISMATCH",
            "expected_sha256": recorded,
            "observed_sha256": observed,
            "size_bytes": size,
        }
    return results


def verify_run(root: Path, run_dir: Path, study: Path, exporter: Path) -> dict[str, object]:
    if run_dir.is_symlink() or not run_dir.is_dir():
        raise ValueError("Run directory must be regular")
    manifest_hash, manifest_size = file_hash(run_dir / "diagnostic_manifest.json")
    capture_hash, capture_size = file_hash(run_dir / "tos_swing_capture.csv")
    try:
        record = json.loads((run_dir / "diagnostic_manifest.json").read_bytes())
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("Invalid diagnostic manifest JSON") from exc
    if not isinstance(record, dict) or record.get("contract") != "tae-tos-001-v2":
        raise ValueError("Unsupported diagnostic contract")
    inputs = record.get("inputs")
    paths = {
        "snapshot_raw_sha256": root / "input_snapshot.json",
        "high_report_sha256": root / "StrategyReports_TMF_HIGHS.csv",
        "low_report_sha256": root / "StrategyReports_TMF_LOWS.csv",
        "study_source_sha256": study,
        "exporter_source_sha256": exporter,
    }
    if not isinstance(inputs, dict) or set(inputs) != set(paths):
        raise ValueError("Missing or unexpected manifest input keys")
    if any(
        not isinstance(inputs[key], str)
        or len(inputs[key]) != 64
        or any(c not in "0123456789abcdef" for c in inputs[key])
        for key in paths
    ):
        raise ValueError("Malformed input SHA-256")
    observed = {key: file_hash(path)[0] for key, path in paths.items()}
    failures = [key for key in paths if inputs[key] != observed[key]]
    run_id = sha256(canonical_json({"contract": "tae-tos-001-v2", **inputs}))
    if run_dir.name != f"run-{run_id}":
        failures.append("RUN_DIRECTORY_ID")
    if capture_hash != record.get("capture_csv_sha256"):
        failures.append("CAPTURE_CSV_SHA256")
    if record.get("platform_execution_verified") is not False:
        failures.append("PLATFORM_EXECUTION_STATUS")
    if record.get("research_acceptance") != "NOT_ESTABLISHED":
        failures.append("RESEARCH_ACCEPTANCE_STATUS")
    if record.get("verification_warnings"):
        failures.append("VERIFICATION_WARNINGS")
    return {
        "status": "CONSISTENT" if not failures else "INCONSISTENT",
        "failures": failures,
        "manifest_sha256": manifest_hash,
        "manifest_size_bytes": manifest_size,
        "capture_sha256": capture_hash,
        "capture_size_bytes": capture_size,
        "expected_run_id": run_id,
        "platform_execution_verified": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local-only read-only TMF evidence integrity audit")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--study", type=Path)
    parser.add_argument("--exporter", type=Path)
    args = parser.parse_args(argv)
    if args.run_dir is not None and (args.study is None or args.exporter is None):
        parser.error("--run-dir requires --study and --exporter")
    try:
        sources = verify_sources(args.root, OPERATOR_HASHES)
        run = (
            verify_run(args.root, args.run_dir, args.study, args.exporter)
            if args.run_dir is not None
            else None
        )
    except (OSError, ValueError) as exc:
        parser.exit(2, f"Invalid evidence: {exc}\n")
    result = {
        "contract": "tmf-prov-001-byte-audit-v1",
        "sources": sources,
        "immutable_run": run,
        "platform_execution_verified": False,
        "full_bar_equivalence_verified": False,
        "research_acceptance": "NOT_ESTABLISHED",
    }
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    complete = all(value["status"] == "MATCH" for value in sources.values())
    return 0 if complete and (run is None or run["status"] == "CONSISTENT") else 1


if __name__ == "__main__":
    raise SystemExit(main())
