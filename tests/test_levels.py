"""Causal support/resistance event-ledger contract tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest

from technical_engine.data import OHLCVBar, OHLCVDataset
from technical_engine.levels import LevelConfig, latest_levels, level_events
from technical_engine.structure import SwingConfig


def fixture(highs, lows):
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
            snapshot_id="levels-test-v1",
        )
        for i, (hi, lo) in enumerate(zip(highs, lows, strict=True))
    )
    return OHLCVDataset(bars=bars, snapshot_id="levels-test-v1")


def test_same_kind_nearby_swings_update_original_level():
    data = fixture(
        [10, 15, 11, 15.03, 10, 17, 12],
        [7, 9, 8, 9, 7, 9, 8],
    )
    events = level_events(data, LevelConfig(swing=SwingConfig(1, 1), merge_tolerance_bps=50))
    resistance = [event for event in events if event.kind == "RESISTANCE"]
    assert [event.swing_count for event in resistance] == [1, 2, 1]
    assert resistance[0].level_id == resistance[1].level_id
    assert resistance[0].anchor_price == resistance[1].anchor_price == 15
    assert resistance[1].mean_price == pytest.approx(15.015)
    assert resistance[1].minimum_price == 15
    assert resistance[1].maximum_price == 15.03
    assert resistance[2].level_id != resistance[1].level_id
    assert resistance[0].confirmation_index == 2
    assert resistance[1].confirmation_index == 4


def test_support_and_resistance_never_share_cluster():
    data = fixture([11, 14, 12, 14, 12, 14, 12], [8, 10, 7, 10, 7.02, 10, 8])
    events = level_events(data, LevelConfig(SwingConfig(1, 1), 50))
    support = [event for event in events if event.kind == "SUPPORT"]
    resistance = [event for event in events if event.kind == "RESISTANCE"]
    assert len(support) == 2
    assert support[-1].swing_count == 2
    assert len(resistance) == 3
    assert resistance[-1].swing_count == 3
    assert support[0].level_id.startswith("S-")
    assert resistance[0].level_id.startswith("R-")
    assert {e.level_id for e in support}.isdisjoint(e.level_id for e in resistance)


def test_prefix_invariance_and_no_retroactive_changes():
    data = fixture([11, 15, 10, 15.02, 11, 16, 10], [8, 9, 7, 8, 7, 8, 6])
    config = LevelConfig(SwingConfig(1, 1), 50)
    full = level_events(data, config)
    for size in range(1, len(data.bars) + 1):
        if size == 1:
            continue
        partial = level_events(replace(data, bars=data.bars[:size]), config)
        assert partial == tuple(e for e in full if e.confirmation_index < size)


def test_latest_level_snapshots_and_timing():
    data = fixture([11, 15, 10, 15.02, 11, 16, 10], [8, 9, 7, 8, 7, 8, 6])
    events = level_events(data, LevelConfig(SwingConfig(1, 1), 50))
    latest = latest_levels(events)
    assert len(latest) == len({event.level_id for event in events})
    assert sum(e.kind == "RESISTANCE" for e in latest) == 2
    first = next(e for e in events if e.kind == "RESISTANCE")
    updated = next(e for e in latest if e.level_id == first.level_id)
    assert first.swing_count == 1
    assert updated.swing_count == 2
    assert first.pivot_session == data.bars[1].session
    assert first.confirmation_session == data.bars[2].session
    assert updated.usable_at == datetime(2025, 1, 1, tzinfo=UTC)


def test_strict_tolerance_and_validation():
    data = fixture([10, 15, 11, 15.2, 10], [7, 8, 7, 8, 7])
    config = LevelConfig(SwingConfig(1, 1), 0)
    resistance = [e for e in level_events(data, config) if e.kind == "RESISTANCE"]
    assert len(resistance) == 2
    assert len({e.level_id for e in resistance}) == 2
    for kwargs in ({"merge_tolerance_bps": -1}, {"merge_tolerance_bps": float("nan")}, {"merge_tolerance_bps": True}):
        with pytest.raises(ValueError):
            LevelConfig(**kwargs)
    with pytest.raises(TypeError):
        LevelConfig(swing=object())
    with pytest.raises(TypeError):
        level_events(data, object())


def test_invalid_input_rejected_and_empty_ledger():
    data = fixture([10, 12, 10], [7, 8, 7])
    assert level_events(data, LevelConfig(SwingConfig(2, 2))) == ()
    assert latest_levels(()) == ()
    invalid = replace(data.bars[1], low=30)
    with pytest.raises(ValueError):
        level_events(replace(data, bars=(data.bars[0], invalid, data.bars[2])))


def test_reproducible_and_inputs_not_mutated():
    data = fixture([10, 15, 11, 15.03, 10, 17, 12], [7, 9, 8, 9, 7, 9, 8])
    before = data.to_dict()
    first = level_events(data, LevelConfig(SwingConfig(1, 1), 50))
    second = level_events(data, LevelConfig(SwingConfig(1, 1), 50))
    assert first == second
    assert data.to_dict() == before
