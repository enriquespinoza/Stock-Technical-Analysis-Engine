"""Acceptance tests for the causal breakout and follow-up event ledger."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta

import pytest

from technical_engine.data import OHLCVBar, OHLCVDataset
from technical_engine.levels import LevelConfig
from technical_engine.setups import SetupConfig, setup_events
from technical_engine.structure import SwingConfig


def fixture(highs, lows, closes=None):
    closes = [(h + l) / 2 for h, l in zip(highs, lows, strict=True)] if closes is None else closes
    bars = tuple(
        OHLCVBar(
            symbol="TEST",
            session=date(2024, 1, 1) + timedelta(days=i),
            open=close,
            high=high,
            low=low,
            close=close,
            volume=1000.0,
            provider="fixture",
            retrieved_at=datetime(2025, 1, 1, tzinfo=UTC),
            available_at=datetime(2024, 1, 1, 22, tzinfo=UTC) + timedelta(days=i),
            adjustment_policy="unadjusted",
            snapshot_id="setup-fixture-v1",
        )
        for i, (high, low, close) in enumerate(zip(highs, lows, closes, strict=True))
    )
    return OHLCVDataset(bars=bars, snapshot_id="setup-fixture-v1")


def config(**kwargs):
    return SetupConfig(levels=LevelConfig(swing=SwingConfig(1, 1)), **kwargs)


def test_resistance_breakout_retest_and_failure_are_sequential():
    data = fixture(
        [12, 20, 16, 21, 22, 22, 22],
        [8, 15, 11, 16, 19, 19.8, 17],
        [10, 18, 14, 19, 21, 20.5, 18],
    )
    events = setup_events(data, config())
    resistance = [e for e in events if e.direction == "UP"]
    assert [e.kind for e in resistance] == ["BREAKOUT", "RETEST", "FAILED_BREAKOUT"]
    assert [e.observation_index for e in resistance] == [4, 5, 6]
    assert all(e.breakout_index == 4 for e in resistance)
    assert all(e.level_anchor_price == 20 for e in resistance)
    assert all(e.level_confirmation_index == 2 for e in resistance)
    assert len({e.breakout_id for e in resistance}) == 1


def test_support_breakdown_retest_and_failure_are_sequential():
    data = fixture(
        [14, 17, 14, 16, 13, 12, 16],
        [10, 11, 7, 10, 6, 6, 6],
        [12, 14, 10, 12, 6.5, 6.8, 10],
    )
    events = setup_events(data, config())
    support = [e for e in events if e.direction == "DOWN"]
    assert [e.kind for e in support] == ["BREAKOUT", "RETEST", "FAILED_BREAKOUT"]
    assert [e.observation_index for e in support] == [4, 5, 6]
    assert all(e.level_anchor_price == 7 for e in support)


def test_breakout_requires_prior_confirmed_level_and_close_crossing():
    data = fixture(
        [12, 20, 16, 21, 22],
        [8, 15, 11, 16, 19],
        [10, 18, 14, 19, 21],
    )
    events = setup_events(data, config())
    assert [(e.kind, e.observation_index) for e in events if e.direction == "UP"] == [
        ("BREAKOUT", 4)
    ]
    assert not any(e.observation_index <= e.level_confirmation_index for e in events)


def test_no_breakout_on_wick_only_or_level_confirmation_bar():
    data = fixture([12, 20, 23, 22], [8, 15, 11, 10], [10, 18, 18, 18])
    assert setup_events(data, config()) == ()


def test_buffer_blocks_small_crossings():
    data = fixture(
        [12, 20, 16, 21, 22],
        [8, 15, 11, 16, 19],
        [10, 18, 14, 19, 20.01],
    )
    assert any(e.kind == "BREAKOUT" for e in setup_events(data, config()))
    assert not any(e.kind == "BREAKOUT" for e in setup_events(data, config(breakout_buffer_bps=20)))


def test_expiry_and_no_followup_on_breakout_bar():
    data = fixture(
        [12, 20, 16, 22, 23, 23, 23, 23],
        [8, 15, 11, 16, 19, 21, 21, 18],
        [10, 18, 14, 19, 21, 22, 22, 19],
    )
    events = [e for e in setup_events(data, config(max_followup_bars=2)) if e.direction == "UP"]
    assert [e.kind for e in events] == ["BREAKOUT"]


def test_prefix_invariance_and_reproducible_frozen_events():
    data = fixture(
        [12, 20, 16, 21, 22, 22, 22],
        [8, 15, 11, 16, 19, 19.8, 17],
        [10, 18, 14, 19, 21, 20.5, 18],
    )
    before = data.to_dict()
    full = setup_events(data, config())
    assert full == setup_events(data, config())
    assert data.to_dict() == before
    for n in range(1, len(data.bars) + 1):
        subset = replace(data, bars=data.bars[:n])
        assert setup_events(subset, config()) == tuple(
            e for e in full if e.observation_index < n
        )
    with pytest.raises(FrozenInstanceError):
        full[0].kind = "RETEST"


def test_backfilled_event_usable_only_after_retrieval():
    data = fixture(
        [12, 20, 16, 21, 22],
        [8, 15, 11, 16, 19],
        [10, 18, 14, 19, 21],
    )
    events = setup_events(data, config())
    assert events
    assert all(e.usable_at == datetime(2025, 1, 1, tzinfo=UTC) for e in events)
    assert all(e.snapshot_id == data.snapshot_id for e in events)


def test_invalid_input_and_configuration():
    data = fixture([12, 20, 16], [8, 15, 11])
    with pytest.raises(TypeError):
        setup_events(data, object())
    with pytest.raises(TypeError):
        SetupConfig(levels=object())
    for kwargs in (
        {"max_followup_bars": 0},
        {"max_followup_bars": True},
        {"retest_tolerance_bps": -1},
        {"breakout_buffer_bps": 10000},
        {"breakout_buffer_bps": float("nan")},
        {"retest_tolerance_bps": True},
    ):
        with pytest.raises(ValueError):
            SetupConfig(**kwargs)
    invalid = replace(data.bars[0], low=30)
    with pytest.raises(ValueError):
        setup_events(replace(data, bars=(invalid, *data.bars[1:])))


def test_monotonic_prices_and_short_history_yield_no_events():
    data = fixture([12, 13, 14, 15], [8, 9, 10, 11])
    assert setup_events(data, config()) == ()
    assert setup_events(replace(data, bars=data.bars[:1]), config()) == ()
