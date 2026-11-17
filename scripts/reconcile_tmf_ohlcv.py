"""Reconcile local TMF Strategy Report bars with an independent Tiingo capture.

All raw data and per-session differences remain local. The script never fetches
market data, modifies evidence, asserts platform execution or grants acceptance.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import shutil
import tempfile
from collections import Counter
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

CONTRACT = "tmf-prov-001-full-bar-reconciliation-v1"
FIELDS = ("open", "high", "low", "close", "volume")
OHLC = FIELDS[:4]
RAW_SHA256 = "cc0d099ab35859cb0106ff1959b7c14f97a96ed55fc3c75b314dc09f0dd3bdbe"
RECOVERED_EXPORTER_SHA256 = "d41ece8f8c18c3fe5ef13c7da03acf1bf1a30f717a8348378441f4e39dc6ab49"
REPORT_HEADER = "Id;Strategy;Side;Amount;Price;Date/Time;Trade P/L;P/L;Position;"
LABEL_PREFIX = "TAE_TMF_OHLCV_Export(OHLCV|TMF|"
EXIT_LABEL = "TAE_TMF_OHLCV_Export(ExportExit)"


def _source_bytes(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Evidence must be a regular file: {path}")
    return path.read_bytes()


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _number(value: object) -> Decimal:
    try:
        result = Decimal(str(value).replace(",", ""))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Invalid numeric OHLCV field") from exc
    if not result.is_finite():
        raise ValueError("Non-finite OHLCV field")
    return result


def _session(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Invalid session type")
    day = date.fromisoformat(value)
    if day.isoformat() != value:
        raise ValueError("Session is not a canonical ISO date")
    return value


def _ordered_dates(dates: list[str], label: str, expected_count: int) -> None:
    if len(dates) != expected_count or dates != sorted(set(dates)):
        raise ValueError(f"{label} must contain {expected_count} unique increasing sessions")


def _valid_bar(row: dict[str, object]) -> None:
    if any(row[field] <= 0 for field in OHLC) or row["volume"] < 0:
        raise ValueError("Invalid nonpositive OHLC or negative volume")
    if not (
        row["low"]
        <= min(row["open"], row["close"])
        <= max(row["open"], row["close"])
        <= row["high"]
    ):
        raise ValueError("Inconsistent OHLC relationships")


def _parse_report(raw: bytes, expected_count: int) -> list[dict[str, object]]:
    lines = raw.decode("utf-8-sig").splitlines()
    if len(lines) < 7 or lines[0].strip() != "Strategy report":
        raise ValueError("Missing thinkorswim report title")
    if lines[1].strip() != "Symbol: TMF":
        raise ValueError("Unexpected thinkorswim report symbol")
    headers = [i for i, line in enumerate(lines) if line.strip() == REPORT_HEADER]
    if len(headers) != 1:
        raise ValueError("Expected one Strategy Report trade header")
    bars: list[dict[str, object]] = []
    exits = 0
    trade_rows = 0
    for line in lines[headers[0] + 1 :]:
        if not re.match(r"^\d+;", line):
            if "TAE_TMF_OHLCV_Export" in line:
                raise ValueError("Unrecognized source export line")
            continue
        row = next(csv.reader([line], delimiter=";", strict=True))
        trade_rows += 1
        if len(row) != 10 or row[-1] != "":
            raise ValueError("Malformed thinkorswim trade record")
        label, side = row[1].strip(), row[2].strip()
        if label == EXIT_LABEL:
            if side != "Sell to Close":
                raise ValueError("Unexpected export exit side")
            exits += 1
            continue
        if not label.startswith(LABEL_PREFIX) or not label.endswith(")"):
            raise ValueError("Unexpected OHLCV export label")
        if side != "Buy to Open":
            raise ValueError("Unexpected OHLCV trade side")
        parts = label[len(LABEL_PREFIX) : -1].split("|")
        if len(parts) != len(FIELDS):
            raise ValueError("Unexpected source OHLCV field count")
        trade_date = datetime.strptime(row[5].strip(), "%m/%d/%y").date().isoformat()
        value = {"session": trade_date, **dict(zip(FIELDS, map(_number, parts), strict=True))}
        _valid_bar(value)
        bars.append(value)
    if len(bars) != expected_count or exits != expected_count or trade_rows != 2 * expected_count:
        raise ValueError("Unexpected Strategy Report trade/exit record counts")
    _ordered_dates([str(row["session"]) for row in bars], "Original report", expected_count)
    return bars


def _parse_csv(raw: bytes, expected_count: int) -> list[dict[str, object]]:
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""))
    if reader.fieldnames != ["session", *FIELDS]:
        raise ValueError("Unexpected normalized CSV columns")
    rows = []
    for row in reader:
        if None in row or any(value is None for value in row.values()):
            raise ValueError("Incomplete normalized CSV row")
        rows.append(
            {
                "session": _session(row["session"]),
                **{field: _number(row[field]) for field in FIELDS},
            }
        )
        _valid_bar(rows[-1])
    _ordered_dates([str(row["session"]) for row in rows], "Normalized CSV", expected_count)
    return rows


def _parse_snapshot(raw: bytes, expected_count: int) -> list[dict[str, object]]:
    dataset = json.loads(raw, parse_float=Decimal)
    if not isinstance(dataset, dict) or not isinstance(dataset.get("bars"), list):
        raise ValueError("Invalid frozen snapshot")
    rows = []
    for bar in dataset["bars"]:
        if not isinstance(bar, dict) or bar.get("symbol") != "TMF":
            raise ValueError("Unexpected snapshot bar or symbol")
        rows.append(
            {
                "session": _session(bar["session"]),
                **{field: _number(bar[field]) for field in FIELDS},
            }
        )
        _valid_bar(rows[-1])
    _ordered_dates([str(row["session"]) for row in rows], "Snapshot", expected_count)
    return rows


def _parse_reference(raw: bytes, expected_count: int) -> list[dict[str, object]]:
    bars = json.loads(raw, parse_float=Decimal)
    if not isinstance(bars, list):
        raise ValueError("Tiingo response must be an array")
    required = {*FIELDS, *("adj" + field.title() for field in FIELDS), "splitFactor", "divCash"}
    rows = []
    for bar in bars:
        if not isinstance(bar, dict) or not isinstance(bar.get("date"), str):
            raise ValueError("Malformed Tiingo record")
        if not required <= bar.keys():
            raise ValueError("Missing required Tiingo fields")
        rows.append(
            {
                "session": _session(bar["date"][:10]),
                **{field: _number(bar[field]) for field in required},
            }
        )
        _valid_bar(rows[-1])
    _ordered_dates([str(row["session"]) for row in rows], "Tiingo", expected_count)
    return rows


def _assert_equal_stream(
    left: list[dict[str, object]], right: list[dict[str, object]], label: str
) -> None:
    for index, (first, second) in enumerate(zip(left, right, strict=True)):
        if first != second:
            raise ValueError(f"{label} differs at row index {index}; stopping without report")


def _classify_volume(delta: Decimal) -> str:
    if delta == 0:
        return "exact"
    size = abs(delta)
    if size < 1:
        return "positive_subshare" if delta > 0 else "negative_subshare"
    if size < 100:
        return "positive_intermediate" if delta > 0 else "negative_intermediate"
    return "positive_material" if delta > 0 else "negative_material"


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode("utf-8")


def reconcile(
    root: Path,
    *,
    expected_source_sha256: str = RAW_SHA256,
    expected_count: int = 249,
    first_session: str = "2025-10-28",
    last_session: str = "2026-10-23",
) -> tuple[dict[str, object], list[dict[str, object]]]:
    """Return summary and local-only 249-row difference ledger; no writes."""
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Evidence root must be a regular directory")
    paths = {
        "original": root / "StrategyReports_TMF_OHLCV.csv",
        "converted": root / "tmf_daily_ohlcv.csv",
        "snapshot": root / "input_snapshot.json",
        "metadata": root / "source_metadata.json",
        "reference": root / "reference/tiingo/tmf_eod_original.json",
        "reference_manifest": root / "reference/tiingo/manifest.json",
    }
    raw = {name: _source_bytes(path) for name, path in paths.items()}
    digests = {name: _digest(data) for name, data in raw.items()}
    exporter = root / "platform_sources/TAE_TMF_OHLCV_Export.ts"
    exporter_status = "NOT_PRESENT"
    if exporter.exists() or exporter.is_symlink():
        recovered = _source_bytes(exporter)
        digests["recovered_exporter_candidate"] = _digest(recovered)
        if digests["recovered_exporter_candidate"] != RECOVERED_EXPORTER_SHA256:
            raise ValueError("Recovered exporter differs from operator-reported fingerprint")
        exporter_status = "RECOVERED_BYTES_MATCH_REPORTED_HASH_NOT_EXECUTION_ATTESTED"
    metadata = json.loads(raw["metadata"])
    manifest = json.loads(raw["reference_manifest"])
    if not isinstance(metadata, dict) or not isinstance(manifest, dict):
        raise ValueError("Invalid provenance metadata")
    if digests["original"] != expected_source_sha256:
        raise ValueError("Original Strategy Report hash differs from audited fingerprint")
    if (
        metadata.get("source_sha256") != digests["original"]
        or metadata.get("snapshot_sha256") != digests["snapshot"]
    ):
        raise ValueError("Original source/snapshot hashes disagree with provenance")
    if (
        manifest.get("sha256") != digests["reference"]
        or manifest.get("bar_count") != expected_count
        or manifest.get("ticker") != "TMF"
    ):
        raise ValueError("Tiingo response hash, ticker, or count disagrees with manifest")
    if (manifest.get("requested_start"), manifest.get("requested_end")) != (
        first_session,
        last_session,
    ):
        raise ValueError("Tiingo manifest request range is not the specified review interval")
    if (
        manifest.get("http_status") != 200
        or "json" not in str(manifest.get("content_type", "")).lower()
    ):
        raise ValueError("Tiingo manifest lacks successful JSON response provenance")
    try:
        retrieved_at = datetime.fromisoformat(manifest["retrieved_at_utc"])
    except (TypeError, KeyError, ValueError) as exc:
        raise ValueError("Tiingo retrieval timestamp is missing or invalid") from exc
    if retrieved_at.tzinfo is None or retrieved_at.utcoffset() != timedelta(0):
        raise ValueError("Tiingo retrieval timestamp must be in UTC")

    report = _parse_report(raw["original"], expected_count)
    normalized = _parse_csv(raw["converted"], expected_count)
    snapshot = _parse_snapshot(raw["snapshot"], expected_count)
    reference = _parse_reference(raw["reference"], expected_count)
    _assert_equal_stream(report, normalized, "Original report to normalized CSV")
    _assert_equal_stream(normalized, snapshot, "Normalized CSV to snapshot")
    dates = [str(row["session"]) for row in report]
    if dates != [str(row["session"]) for row in reference]:
        raise ValueError("Tiingo sessions and original report sessions differ")
    if (dates[0], dates[-1]) != (first_session, last_session):
        raise ValueError("Unexpected comparison boundary dates")

    raw_match = Counter()
    adjusted_match = Counter()
    volume_categories = Counter()
    price_sessions = []
    material_sessions = []
    fractional_sessions = []
    rounding_matches = 0
    truncation_matches = 0
    adjusted_volume_matches = 0
    ledger = []
    for observed, vendor in zip(report, reference, strict=True):
        session = str(observed["session"])
        price_deltas = {}
        for field in OHLC:
            difference = observed[field] - vendor[field]
            if difference == 0:
                raw_match[field] += 1
            else:
                price_deltas[field] = str(difference)
            if observed[field] == vendor["adj" + field.title()]:
                adjusted_match[field] += 1
        if price_deltas:
            price_sessions.append(session)
        local_volume = observed["volume"]
        vendor_volume = vendor["volume"]
        delta = local_volume - vendor_volume
        adjusted_volume_matches += int(local_volume == vendor["adjVolume"])
        category = _classify_volume(delta)
        volume_categories[category] += 1
        fractional = local_volume % 1 != 0
        if fractional:
            fractional_sessions.append(session)
        if delta != 0:
            rounding_matches += int(round(local_volume) == vendor_volume)
            truncation_matches += int(int(local_volume) == vendor_volume)
        if category.endswith("material"):
            material_sessions.append(session)
        ledger.append(
            {
                "session": session,
                "price_raw_deltas": price_deltas,
                "volume_delta": str(delta),
                "volume_classification": category,
                "volume_relative_pct": str(Decimal(100) * delta / vendor_volume)
                if vendor_volume != 0
                else None,
                "local_fractional_volume": fractional,
            }
        )
    summary = {
        "contract": CONTRACT,
        "ticker": "TMF",
        "input_sha256": digests,
        "bar_count": expected_count,
        "first_session": dates[0],
        "last_session": dates[-1],
        "source_to_converted_verified": True,
        "converted_to_snapshot_verified": True,
        "reference_session_dates_verified": True,
        "raw_ohlc_exact_matches": {field: raw_match[field] for field in OHLC},
        "raw_ohlc_exact_total": sum(raw_match.values()),
        "adjusted_ohlc_exact_matches": {field: adjusted_match[field] for field in OHLC},
        "price_discrepancy_sessions": price_sessions,
        "volume_categories": dict(volume_categories),
        "adjusted_volume_exact_matches": adjusted_volume_matches,
        "fractional_local_volume_count": len(fractional_sessions),
        "first_fractional_session": fractional_sessions[0] if fractional_sessions else None,
        "material_volume_sessions": material_sessions,
        "rounding_matches_among_volume_mismatches": rounding_matches,
        "truncation_matches_among_volume_mismatches": truncation_matches,
        "tiingo_nonzero_dividend_records": sum(row["divCash"] != 0 for row in reference),
        "tiingo_nonunit_split_records": sum(row["splitFactor"] != 1 for row in reference),
        "recorded_adjustment_policy": metadata.get("adjustment_policy"),
        "reference_retrieved_at_utc": manifest["retrieved_at_utc"],
        "source_capture_timestamp_operator_reported": metadata.get("captured_at"),
        "recovered_exporter_candidate_status": exporter_status,
        "exchange_calendar_independently_verified": False,
        "platform_execution_verified": False,
        "full_bar_equivalence_verified": False,
        "research_acceptance": "NOT_ESTABLISHED",
        "reviewer_disposition": "PENDING",
    }
    return summary, ledger


def save_local_run(
    output_root: Path, summary: dict[str, object], ledger: list[dict[str, object]]
) -> Path:
    """Write an immutable content-addressed run locally; never replace evidence."""
    if output_root.is_symlink():
        raise ValueError("Output root cannot be a symbolic link")
    output_root.mkdir(parents=True, exist_ok=True)
    inputs = summary["input_sha256"]
    run_id = _digest(_json_bytes({"contract": CONTRACT, "input_sha256": inputs}))
    dest = output_root / f"run-{run_id}"
    files = {"summary.json": _json_bytes(summary), "per_session_ledger.json": _json_bytes(ledger)}
    if dest.exists() or dest.is_symlink():
        if dest.is_symlink() or not dest.is_dir():
            raise FileExistsError("Existing run path is not a regular directory")
        if {path.name for path in dest.iterdir()} != set(files):
            raise FileExistsError("Existing run has an unexpected file inventory")
        if any(
            (dest / name).is_symlink() or (dest / name).read_bytes() != data
            for name, data in files.items()
        ):
            raise FileExistsError("Existing run differs; refusing overwrite")
        return dest
    staged = Path(tempfile.mkdtemp(prefix=".tmf-reconcile-stage-", dir=output_root))
    try:
        for name, data in files.items():
            (staged / name).write_bytes(data)
        os.rename(staged, dest)
    finally:
        if staged.exists():
            shutil.rmtree(staged)
    return dest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local-only read-only TMF OHLCV reconciliation")
    parser.add_argument("--root", type=Path, default=Path("parity/tmf_001"))
    parser.add_argument("--no-write", action="store_true", help="Print aggregate summary only")
    args = parser.parse_args(argv)
    try:
        summary, ledger = reconcile(args.root)
        if not args.no_write:
            dest = save_local_run(args.root / "reconciliation", summary, ledger)
            print(f"Local immutable reconciliation: {dest}")
    except (OSError, ValueError, KeyError, csv.Error, json.JSONDecodeError) as exc:
        parser.exit(2, f"Reconciliation blocked: {exc}\n")
    public = {
        key: value
        for key, value in summary.items()
        if key not in ("material_volume_sessions", "price_discrepancy_sessions")
    }
    print(json.dumps(public, indent=2, sort_keys=True))
    # Valid execution is NOT bar equivalence or research acceptance.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
