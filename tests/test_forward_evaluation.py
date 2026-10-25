"""TAE-003 boundary, censoring and reproducibility contract tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta

import pytest

from technical_engine.data import OHLCVBar, OHLCVDataset
from technical_engine.forward_evaluation import ForwardEvaluationConfig, evaluate_forward_returns
from technical_engine.levels import LevelConfig
from technical_engine.setups import SetupConfig, setup_events
from technical_engine.structure import SwingConfig


def fixture():
    highs = [12, 20, 16, 21, 22, 22, 22, 23, 24, 24, 25, 26, 25, 27]
    lows = [8, 15, 11, 16, 19, 19.8, 17, 19, 20, 20, 21, 22, 20, 22]
    closes = [10, 18, 14, 19, 21, 20.5, 18, 21, 22, 23, 24, 25, 21, 26]
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
            snapshot_id="forward-test",
        )
        for i, (high, low, close) in enumerate(zip(highs, lows, closes, strict=True))
    )
    return OHLCVDataset(bars, "forward-test")


def setup_config():
    return SetupConfig(levels=LevelConfig(swing=SwingConfig(1, 1)))


def test_horizon_labels_are_exact_close_to_close_and_directional():
    data = fixture()
    conf = ForwardEvaluationConfig(
        cutoff_session=data.bars[8].session,
        horizons=(1, 2),
        setup=setup_config(),
    )
    outcome = evaluate_forward_returns(data, conf)
    assert outcome.labels
    assert any(label.partition == "HOLDOUT" for label in outcome.labels)
    for label in outcome.labels:
        if label.status == "MATURED":
            assert label.label_end_index == label.observation_index + label.horizon_bars
            assert label.label_end_session == data.bars[label.label_end_index].session
            expected = data.bars[label.label_end_index].close / label.start_close - 1
            assert label.simple_return == expected
            assert label.directional_return == (
                expected if label.event_direction == "UP" else -expected
            )
        else:
            assert label.end_close is None
            assert label.simple_return is None
            assert label.directional_return is None


def test_development_labels_never_cross_holdout_cutoff():
    data = fixture()
    conf = ForwardEvaluationConfig(
        cutoff_session=data.bars[4].session,
        horizons=(1, 3),
        setup=setup_config(),
    )
    outcome = evaluate_forward_returns(data, conf)
    for label in outcome.labels:
        if label.partition == "DEVELOPMENT":
            assert label.label_end_index is None or label.label_end_index <= 4
    assert any(label.status == "CENSORED" for label in outcome.labels)


def test_embargo_excludes_early_holdout_starts():
    data = fixture()
    cutoff = 5
    conf = ForwardEvaluationConfig(
        cutoff_session=data.bars[cutoff].session,
        horizons=(1,),
        embargo_bars=3,
        setup=setup_config(),
    )
    outcome = evaluate_forward_returns(data, conf)
    assert all(
        label.observation_index > cutoff + 3
        for label in outcome.labels if label.partition == "HOLDOUT"
    )


def test_tail_censoring_and_empty_summary_are_not_zero():
    data = fixture()
    conf = ForwardEvaluationConfig(
        cutoff_session=data.bars[5].session,
        horizons=(20,),
        setup=setup_config(),
    )
    outcome = evaluate_forward_returns(data, conf)
    assert outcome.labels
    assert all(label.status == "CENSORED" for label in outcome.labels)
    assert all(summary.matured_count == 0 for summary in outcome.summaries)
    assert all(summary.mean_simple_return is None for summary in outcome.summaries)
    assert all(summary.directional_positive_fraction is None for summary in outcome.summaries)


def test_deterministic_nonmutating_and_immutable():
    data = fixture()
    before = data.to_dict()
    conf = ForwardEvaluationConfig(
        cutoff_session=data.bars[5].session,
        horizons=(1, 3),
        setup=setup_config(),
    )
    first = evaluate_forward_returns(data, conf)
    second = evaluate_forward_returns(data, conf)
    assert first == second
    assert data.to_dict() == before
    assert first.method == "retrospective_chronological_holdout_not_prospective"
    assert first.labels
    with pytest.raises(FrozenInstanceError):
        first.labels[0].start_close = 0


def test_forged_or_cross_snapshot_events_fail_closed():
    data = fixture()
    conf = ForwardEvaluationConfig(data.bars[5].session, (1,), setup=setup_config())
    events = setup_events(data, setup_config())
    assert events
    with pytest.raises(ValueError, match="exactly match"):
        evaluate_forward_returns(data, conf, events=(replace(events[0], close=999),))
    with pytest.raises(TypeError, match="tuple"):
        evaluate_forward_returns(data, conf, events=list(events))


def test_invalid_boundaries_and_configs_rejected():
    data = fixture()
    for kwargs in (
        {"cutoff_session": datetime(2024, 1, 4)},
        {"cutoff_session": data.bars[4].session, "horizons": ()},
        {"cutoff_session": data.bars[4].session, "horizons": (2, 1)},
        {"cutoff_session": data.bars[4].session, "horizons": (1, 1)},
        {"cutoff_session": data.bars[4].session, "horizons": (True,)},
        {"cutoff_session": data.bars[4].session, "embargo_bars": -1},
        {"cutoff_session": data.bars[4].session, "setup": object()},
    ):
        with pytest.raises((TypeError, ValueError)):
            ForwardEvaluationConfig(**kwargs)
    with pytest.raises(ValueError, match="cutoff_session"):
        evaluate_forward_returns(data, ForwardEvaluationConfig(data.bars[-1].session))
    with pytest.raises(TypeError):
        evaluate_forward_returns(data, object())


def test_invalid_dataset_and_frozen_snapshot():
    data = fixture()
    bad = replace(data.bars[1], close=-5)
    with pytest.raises(ValueError):
        evaluate_forward_returns(
            replace(data, bars=(data.bars[0], bad, *data.bars[2:])),
            ForwardEvaluationConfig(data.bars[5].session),
        )
