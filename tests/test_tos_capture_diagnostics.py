"""Synthetic serialization checks for TAE-TOS diagnostic mismatch manifests."""

from __future__ import annotations

from datetime import date

from scripts.build_tos_capture import _difference_json
from technical_engine.artifacts import canonical_json
from technical_engine.tos_parity import ParityDifference, SwingObservation


def test_mismatch_diagnostic_serializes_dates_to_iso_json():
    expected = SwingObservation(
        kind="HIGH",
        pivot_index=2,
        confirmation_index=4,
        pivot_session=date(2024, 1, 4),
        confirmation_session=date(2024, 1, 8),
        price=15.555,
    )
    item = ParityDifference(
        kind="MISSING",
        key=("HIGH", 2, 4),
        expected=expected,
        observed=None,
    )
    obj = _difference_json(item)
    assert obj["key"] == ["HIGH", 2, 4]
    assert obj["expected"]["pivot_session"] == "2024-01-04"
    assert obj["expected"]["confirmation_session"] == "2024-01-08"
    assert obj["observed"] is None
    assert b"2024-01-08" in canonical_json(obj)
