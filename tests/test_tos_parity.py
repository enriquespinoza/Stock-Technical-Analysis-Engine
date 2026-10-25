"""Synthetic parity comparisons; no actual thinkorswim execution implied."""

from __future__ import annotations

import csv
import io
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from technical_engine.artifacts import canonical_json, sha256
from technical_engine.data import OHLCVBar, OHLCVDataset
from technical_engine.structure import SwingConfig, confirmed_swings
from technical_engine.tos_parity import (
    ThinkScriptCapture,
    compare_swing_capture,
    parse_swing_capture,
)

STUDY = b"script source pinned for testing"


@pytest.fixture
def dataset():
    highs = (12, 20, 16, 21, 22, 22, 22)
    lows = (8, 15, 11, 16, 19, 19.8, 17)
    closes = (10, 18, 14, 19, 21, 20.5, 18)
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
            snapshot_id="parity-test",
        )
        for i, (high, low, close) in enumerate(zip(highs, lows, closes, strict=True))
    )
    return OHLCVDataset(bars, "parity-test")


def capture_info(dataset):
    return ThinkScriptCapture(
        symbol="TEST",
        aggregation="DAY",
        snapshot_sha256=sha256(canonical_json(dataset.to_dict())),
        study_sha256=sha256(STUDY),
        captured_at=datetime(2025, 1, 2, tzinfo=UTC),
        bar_count=len(dataset.bars),
        first_session=dataset.bars[0].session,
        last_session=dataset.bars[-1].session,
    )


def rows_csv(rows):
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow((
        "kind", "pivot_index", "confirmation_index",
        "pivot_session", "confirmation_session", "price",
    ))
    for row in rows:
        writer.writerow(row)
    return output.getvalue()


def python_rows(dataset):
    return [
        (
            event.kind,
            event.pivot_index,
            event.confirmation_index,
            event.pivot_session.isoformat(),
            event.confirmation_session.isoformat(),
            event.price,
        )
        for event in confirmed_swings(dataset, SwingConfig(1, 1))
    ]


def test_matching_synthetic_csv_never_claims_platform_attestation(dataset):
    rows = python_rows(dataset)
    assert rows
    report = compare_swing_capture(
        dataset,
        SwingConfig(1, 1),
        rows_csv(rows),
        capture=capture_info(dataset),
        study_source=STUDY,
    )
    assert report.comparison_complete
    assert report.matched_count == len(rows)
    assert report.differences == ()
    assert report.platform_execution_verified is False
    assert report.research_acceptance == "NOT_ESTABLISHED"


def test_missing_extra_and_wrong_prices_are_explicit(dataset):
    original = python_rows(dataset)
    modified = [*original[1:]]
    modified[0] = (*modified[0][:-1], modified[0][-1] + 5)
    modified.append(("HIGH", 0, 1, "2024-01-01", "2024-01-02", 17))
    report = compare_swing_capture(
        dataset,
        SwingConfig(1, 1),
        rows_csv(modified),
        capture=capture_info(dataset),
        study_source=STUDY,
    )
    assert not report.comparison_complete
    assert {difference.kind for difference in report.differences} == {
        "MISSING", "EXTRA", "PRICE_MISMATCH",
    }


def test_reject_bad_csv_duplicates_and_causality():
    valid = ("HIGH", 1, 2, "2024-01-02", "2024-01-03", 20)
    for csv_text in (
        "wrong,header\n",
        rows_csv([valid, valid]),
        rows_csv([("HIGH", 1, 1, "2024-01-02", "2024-01-03", 20)]),
        rows_csv([("HIGH", 1, 2, "2024-01-03", "2024-01-02", 20)]),
        rows_csv([("INVALID", 1, 2, "2024-01-02", "2024-01-03", 20)]),
        rows_csv([("HIGH", 1, 2, "2024-01-02", "2024-01-03", "NaN")]),
    ):
        with pytest.raises(ValueError):
            parse_swing_capture(csv_text)


def test_identity_and_configuration_mismatch_rejected(dataset):
    rows = rows_csv(python_rows(dataset))
    info = capture_info(dataset)
    for updated in (
        replace(info, snapshot_sha256="a" * 64),
        replace(info, study_sha256="b" * 64),
        replace(info, symbol="WRONG"),
        replace(info, bar_count=8),
        replace(info, last_session=date(2024, 2, 1)),
    ):
        with pytest.raises(ValueError, match="source identity"):
            compare_swing_capture(
                dataset, SwingConfig(1, 1), rows, capture=updated, study_source=STUDY
            )
    with pytest.raises(ValueError, match="source identity"):
        compare_swing_capture(
            dataset, SwingConfig(1, 1), rows, capture=info, study_source=b"other"
        )


def test_tolerance_is_explicit_and_never_relative(dataset):
    rows = python_rows(dataset)
    changed = [(*row[:-1], row[-1] + 0.005) for row in rows]
    for tolerance, expected in ((0.001, False), (0.01, True)):
        report = compare_swing_capture(
            dataset,
            SwingConfig(1, 1),
            rows_csv(changed),
            capture=capture_info(dataset),
            study_source=STUDY,
            price_absolute_tolerance=tolerance,
        )
        assert report.comparison_complete is expected
    with pytest.raises(ValueError, match="tolerance"):
        compare_swing_capture(
            dataset, SwingConfig(1, 1), rows_csv(rows),
            capture=capture_info(dataset), study_source=STUDY,
            price_absolute_tolerance=float("nan"),
        )
