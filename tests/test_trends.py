"""Acceptance tests for causal, descriptive trend-event classifications."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta

import pytest

from technical_engine.data import OHLCVBar, OHLCVDataset
from technical_engine.structure import SwingConfig, confirmed_swings
from technical_engine.trends import TrendConfig, latest_trend, trend_events


def fixture(highs, lows, *, retrieved_at=None):
    captured = retrieved_at or datetime(2025, 1, 1, tzinfo=UTC)
    bars = tuple(
        OHLCVBar(
            symbol="TEST",
            session=date(2024, 1, 1) + timedelta(days=i),
            open=(hi + lo) / 2,
            high=hi,
            low=lo,
            close=(hi + lo) / 2,
            volume=1000.0,
            provider="fixture",
            retrieved_at=captured,
            available_at=datetime(2024, 1, 1, 22, tzinfo=UTC) + timedelta(days=i),
            adjustment_policy="unadjusted",
            snapshot_id="trend-fixture-v1",
        )
        for i, (hi, lo) in enumerate(zip(highs, lows, strict=True))
    )
    return OHLCVDataset(bars=bars, snapshot_id="trend-fixture-v1")


def config(tolerance=0.0):
    return TrendConfig(SwingConfig(left=1, right=1), comparison_tolerance_bps=tolerance)


def test_rising_structure_requires_two_confirmed_highs_and_lows():
    data = fixture(
        [12, 20, 13, 22, 14, 24, 15, 16],
        [8, 15, 7, 16, 9, 17, 10, 11],
    )
    events = trend_events(data, config())
    assert [(e.swing_kind, e.pivot_index, e.confirmation_index) for e in events] == [
        ("HIGH", 1, 2),
        ("LOW", 2, 3),
        ("HIGH", 3, 4),
        ("LOW", 4, 5),
        ("HIGH", 5, 6),
        ("LOW", 6, 7),
    ]
    assert [e.state for e in events] == [
        "INDETERMINATE",
        "INDETERMINATE",
        "INDETERMINATE",
        "UPTREND",
        "UPTREND",
        "UPTREND",
    ]
    assert events[3].high_structure == "HH"
    assert events[3].low_structure == "HL"
    assert events[3].confirmation_session == data.bars[5].session
    assert events[3].pivot_session == data.bars[4].session
    assert latest_trend(events) == events[-1]


def test_falling_structure_classifies_downtrend():
    data = fixture(
        [16, 24, 15, 22, 14, 20, 13, 18],
        [12, 18, 11, 17, 9, 16, 7, 15],
    )
    events = trend_events(data, config())
    assert events[3].state == "DOWNTREND"
    assert events[-1].state == "DOWNTREND"
    assert events[-1].high_structure == "LH"
    assert events[-1].low_structure == "LL"


def test_equal_extrema_and_mixed_structure_are_sideways():
    equal = fixture(
        [12, 20, 13, 20, 14, 20, 15],
        [8, 15, 7, 16, 7, 17, 10],
    )
    states = trend_events(equal, config())
    assert states[-1].high_structure == "EH"
    assert states[-1].low_structure == "EL"
    assert states[-1].state == "SIDEWAYS"

    mixed = fixture(
        [12, 20, 13, 22, 14, 24, 15],
        [8, 15, 7, 16, 6, 17, 10],
    )
    events = trend_events(mixed, config())
    assert events[-1].high_structure == "HH"
    assert events[-1].low_structure == "LL"
    assert events[-1].state == "SIDEWAYS"


def test_comparison_tolerance_makes_near_equal_prices_equal():
    data = fixture(
        [12, 20, 13, 20.001, 14, 20.002, 15],
        [8, 15, 7, 16, 7.001, 17, 10],
    )
    strict = trend_events(data, config(0))
    tolerant = trend_events(data, config(10))
    assert strict[-1].high_structure == "HH"
    assert strict[-1].low_structure == "HL"
    assert strict[-1].state == "UPTREND"
    assert tolerant[-1].high_structure == "EH"
    assert tolerant[-1].low_structure == "EL"
    assert tolerant[-1].state == "SIDEWAYS"


def test_prefix_invariance_and_deterministic_replay():
    data = fixture(
        [12, 20, 13, 22, 14, 24, 15, 16],
        [8, 15, 7, 16, 9, 17, 10, 11],
    )
    before = data.to_dict()
    full = trend_events(data, config())
    assert full == trend_events(data, config())
    assert data.to_dict() == before
    for size in range(1, len(data.bars) + 1):
        prefix = replace(data, bars=data.bars[:size])
        # The underlying data contract requires at least one observation.
        partial = trend_events(prefix, config())
        assert partial == tuple(e for e in full if e.confirmation_index < size)
    assert len(full) == len(confirmed_swings(data, config().swing))


def test_retrieval_time_prevents_backdating_and_immutable_events():
    backfill = datetime(2025, 1, 1, tzinfo=UTC)
    data = fixture(
        [12, 20, 13, 22, 14, 24, 15, 16],
        [8, 15, 7, 16, 9, 17, 10, 11],
        retrieved_at=backfill,
    )
    events = trend_events(data, config())
    assert all(e.usable_at == backfill for e in events)
    assert all(e.confirmation_session >= e.pivot_session for e in events)
    assert all(e.snapshot_id == data.snapshot_id for e in events)
    with pytest.raises(FrozenInstanceError):
        events[-1].state = "SIDEWAYS"


def test_empty_history_of_confirmed_swings_and_latest():
    data = fixture([10, 11, 12], [5, 6, 7])
    assert trend_events(data, config()) == ()
    assert latest_trend(()) is None


def test_invalid_inputs_rejected():
    data = fixture([10, 13, 11], [7, 8, 6])
    invalid_bar = replace(data.bars[0], low=20)
    with pytest.raises(ValueError):
        trend_events(replace(data, bars=(invalid_bar, *data.bars[1:])), config())
    with pytest.raises(TypeError):
        TrendConfig(swing=object())
    with pytest.raises(TypeError):
        trend_events(data, object())
    for tolerance in (-1, float("nan"), float("inf"), True, "10"):
        with pytest.raises(ValueError):
            TrendConfig(comparison_tolerance_bps=tolerance)


def test_reversals_reflect_only_newly_confirmed_structure():
    data = fixture(
        [12, 20, 13, 22, 14, 24, 15, 19, 13, 17, 12, 16, 11],
        [8, 15, 7, 16, 9, 17, 10, 15, 8, 14, 7, 13, 6],
    )
    events = trend_events(data, config())
    assert any(e.state == "UPTREND" for e in events)
    assert events[-1].state == "DOWNTREND"
    assert events[-1].high_structure == "LH"
    assert events[-1].low_structure == "LL"
    first_up = next(i for i, e in enumerate(events) if e.state == "UPTREND")
    first_down = next(i for i, e in enumerate(events) if e.state == "DOWNTREND")
    assert first_down > first_up
    assert all(e.event_index == i for i, e in enumerate(events))
