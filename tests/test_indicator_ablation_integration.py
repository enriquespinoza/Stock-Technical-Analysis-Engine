"""Nonempty synthetic TAE-005B integration and censoring regressions."""

from __future__ import annotations

import math
from dataclasses import replace
from datetime import timedelta

from test_forward_evaluation import fixture, setup_config

from technical_engine.data import OHLCVDataset
from technical_engine.forward_evaluation import ForwardEvaluationConfig, evaluate_forward_returns
from technical_engine.indicator_ablation import AblationPlan, audit_indicator_ablations
from technical_engine.statistical_protocol import StatisticalHypothesis, StatisticalProtocolPlan

_KEYS = (
    "rsi_14",
    "ema_9",
    "ema_21",
    "roc_10",
    "macd_histogram_12_26_9",
    "atr_14",
)


def longer_fixture() -> OHLCVDataset:
    """Extend an existing real-event fixture into multiple synthetic cycles."""
    source = fixture()
    first = source.bars[0]
    snapshot_id = "ablation-long-synthetic"
    bars = tuple(
        replace(
            source.bars[index % len(source.bars)],
            session=first.session + timedelta(days=index),
            available_at=first.available_at + timedelta(days=index),
            snapshot_id=snapshot_id,
        )
        for index in range(140)
    )
    return OHLCVDataset(bars, snapshot_id)


def long_plan(dataset: OHLCVDataset, horizon: int = 1) -> AblationPlan:
    return AblationPlan(
        statistical=StatisticalProtocolPlan(
            study_id="ABLATION_NONEMPTY_FIXTURE",
            forward=ForwardEvaluationConfig(
                cutoff_session=dataset.bars[60].session,
                horizons=(horizon,),
                embargo_bars=1,
                setup=setup_config(),
            ),
            hypotheses=(StatisticalHypothesis("H1", "BREAKOUT", horizon),),
        )
    )


def test_actual_indicators_produce_nonempty_matured_baseline():
    data = longer_fixture()
    spec = long_plan(data)
    report = audit_indicator_ablations(data, spec)
    holdout = next(
        row
        for row in report.rows
        if row.partition == "HOLDOUT" and row.treatment == "UNFILTERED_ELIGIBLE"
    )
    assert holdout.matured_count > 0
    assert holdout.mean_directional_return is not None
    assert holdout.matured_count <= holdout.eligible_count
    assert report == audit_indicator_ablations(data, spec)


def test_nonempty_all_contexts_vs_leave_rsi_out(monkeypatch):
    data = longer_fixture()
    spec = long_plan(data)
    evaluation = evaluate_forward_returns(data, spec.statistical.forward)
    candidates = [
        label
        for label in evaluation.labels
        if label.partition == "HOLDOUT"
        and label.event_kind == "BREAKOUT"
        and label.horizon_bars == 1
        and label.status == "MATURED"
    ]
    choices = []
    used_indices = set()
    for label in candidates:
        if label.observation_index not in used_indices:
            choices.append(label)
            used_indices.add(label.observation_index)
        if len(choices) == 2:
            break
    assert len(choices) == 2, "fixture must exercise two distinct matured breakouts"

    # Supply controlled, deterministic event-time features while retaining
    # real TAE-003 events, partitioning, returns, and censoring.
    features = [{name: None for name in _KEYS} for _ in data.bars]
    for index, label in enumerate(choices):
        close = data.bars[label.observation_index].close
        is_up = label.event_direction == "UP"
        features[label.observation_index] = {
            "rsi_14": (60.0 if is_up else 40.0) if index == 0 else (
                40.0 if is_up else 60.0
            ),
            "ema_9": close - 0.5 if is_up else close + 0.5,
            "ema_21": close - 1.0 if is_up else close + 1.0,
            "roc_10": 1.0 if is_up else -1.0,
            "macd_histogram_12_26_9": 0.5 if is_up else -0.5,
            "atr_14": close * 0.03,
        }
    monkeypatch.setattr(
        "technical_engine.indicator_ablation.compute_features",
        lambda dataset, config: features,
    )
    audit = audit_indicator_ablations(data, spec)
    rows = {row.treatment: row for row in audit.rows if row.partition == "HOLDOUT"}
    baseline = rows["UNFILTERED_ELIGIBLE"]
    all_four = rows["ALL_CONTEXTS"]
    removed_rsi = rows["WITHOUT_RSI"]
    assert baseline.matured_count > 0
    assert all_four.matured_count > 0
    assert removed_rsi.matured_count > all_four.matured_count
    assert removed_rsi.matured_count == baseline.matured_count
    assert baseline.censored_count == removed_rsi.censored_count == 0
    assert all_four.censored_count == 0
    selected_indices = {label.observation_index for label in choices}
    expected = [
        label.directional_return
        for label in candidates
        if label.observation_index in selected_indices
        and label.event_direction
        == next(
            chosen.event_direction
            for chosen in choices
            if chosen.observation_index == label.observation_index
        )
    ]
    expected_mean = math.fsum(expected) / len(expected)
    assert math.isclose(baseline.mean_directional_return, expected_mean, abs_tol=1e-12)
    assert baseline.descriptive_difference == 0
    assert math.isclose(
        removed_rsi.descriptive_difference,
        removed_rsi.mean_directional_return - baseline.mean_directional_return,
        abs_tol=1e-12,
    )
    assert audit.research_acceptance == "NOT_ESTABLISHED"


def test_censored_holdout_is_not_assigned_zero_return(monkeypatch):
    data = longer_fixture()
    spec = long_plan(data, horizon=140)
    # All synthetic features are complete. A horizon of 140 bars on
    # 140 available bars cannot mature even for the first eligible event.
    features = [
        {
            "rsi_14": 55.0,
            "ema_9": bar.close - 0.5,
            "ema_21": bar.close - 1.0,
            "roc_10": 1.0,
            "macd_histogram_12_26_9": 0.5,
            "atr_14": bar.close * 0.03,
        }
        for bar in data.bars
    ]
    monkeypatch.setattr(
        "technical_engine.indicator_ablation.compute_features",
        lambda dataset, config: features,
    )
    report = audit_indicator_ablations(data, spec)
    baseline = next(
        row
        for row in report.rows
        if row.partition == "HOLDOUT" and row.treatment == "UNFILTERED_ELIGIBLE"
    )
    assert baseline.eligible_count > 0
    assert baseline.matured_count == 0
    assert baseline.censored_count == baseline.eligible_count
    assert baseline.mean_directional_return is None
    assert baseline.descriptive_difference is None
