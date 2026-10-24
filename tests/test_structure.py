"""Deterministic checks for causality and swing-point classification."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from technical_engine.data import OHLCVBar, OHLCVDataset
from technical_engine.structure import SwingConfig, confirmed_swings


def dataset(highs, lows=None):
    lows = [x - 3 for x in highs] if lows is None else lows
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
            retrieved_at=datetime(2025, 1, 1, tzinfo=UTC),
            available_at=datetime(2024, 1, 1, 22, tzinfo=UTC) + timedelta(days=i),
            adjustment_policy="unadjusted",
            snapshot_id="swing-fixture-v1",
        )
        for i, (hi, lo) in enumerate(zip(highs, lows, strict=True))
    )
    return OHLCVDataset(bars=bars, snapshot_id="swing-fixture-v1")


def test_known_confirmed_swings_and_delayed_confirmation():
    data = dataset(
        [10, 12, 15, 11, 10, 16, 11, 9],
        [7, 8, 8, 6, 5, 7, 6, 4],
    )
    points = confirmed_swings(data, SwingConfig(left=1, right=1))
    assert [(p.kind, p.pivot_index, p.confirmation_index) for p in points] == [
        ("HIGH", 2, 3),
        ("LOW", 4, 5),
        ("HIGH", 5, 6),
    ]
    assert points[0].pivot_session == data.bars[2].session
    assert points[0].confirmation_session == data.bars[3].session
    assert points[0].usable_at == datetime(2025, 1, 1, tzinfo=UTC)


def test_prefix_invariance_and_no_early_confirmation():
    data = dataset([10, 12, 15, 11, 10, 16, 11, 9])
    config = SwingConfig(left=1, right=1)
    assert confirmed_swings(replace(data, bars=data.bars[:3]), config) == ()
    full = confirmed_swings(data, config)
    for size in range(3, len(data.bars) + 1):
        partial = confirmed_swings(replace(data, bars=data.bars[:size]), config)
        assert partial == tuple(p for p in full if p.confirmation_index < size)


def test_equal_highs_and_flat_bars_have_no_swings():
    assert confirmed_swings(dataset([12, 12, 12, 12, 12]), SwingConfig(1, 1)) == ()
    assert confirmed_swings(dataset([10, 12, 12, 10], [4, 4, 4, 4]), SwingConfig(1, 1)) == ()


def test_tolerance_changes_near_equal_high_classification():
    data = dataset([10, 12.0, 12.00001, 10], [5, 5, 5, 5])
    assert [(p.kind, p.pivot_index) for p in confirmed_swings(data, SwingConfig(1, 1))] == [
        ("HIGH", 2)
    ]
    assert confirmed_swings(data, SwingConfig(1, 1, tolerance_bps=0.2)) == ()


def test_short_history_and_config_validation():
    data = dataset([10, 12, 10])
    assert confirmed_swings(data, SwingConfig(2, 2)) == ()
    for kwargs in (
        {"left": 0},
        {"right": True},
        {"tolerance_bps": -1},
        {"tolerance_bps": float("nan")},
    ):
        with pytest.raises(ValueError):
            SwingConfig(**kwargs)
    with pytest.raises(TypeError):
        confirmed_swings(data, object())


def test_invalid_ohlcv_rejected():
    data = dataset([10, 12, 10])
    bad = replace(data.bars[0], low=20)
    with pytest.raises(ValueError):
        confirmed_swings(replace(data, bars=(bad, *data.bars[1:])), SwingConfig(1, 1))


def test_uses_late_source_availability_and_does_not_mutate():
    data = dataset([10, 12, 15, 11, 10])
    late = replace(data.bars[0], available_at=datetime(2024, 10, 1, tzinfo=UTC))
    adjusted = replace(data, bars=(late, *data.bars[1:]))
    before = adjusted.to_dict()
    points = confirmed_swings(adjusted, SwingConfig(1, 1))
    assert points[0].available_at == late.available_at
    assert adjusted.to_dict() == before
    assert points == confirmed_swings(adjusted, SwingConfig(1, 1))
