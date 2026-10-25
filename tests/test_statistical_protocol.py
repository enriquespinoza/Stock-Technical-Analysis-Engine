"""TAE-005A synthetic plan, censoring and dependence audit tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from technical_engine.forward_evaluation import ForwardEvaluationConfig, evaluate_forward_returns
from technical_engine.statistical_protocol import (
    StatisticalHypothesis,
    StatisticalProtocolPlan,
    _dependencies,
    audit_statistical_protocol,
)
from test_forward_evaluation import fixture, setup_config


def plan(data, *, horizons=(1, 3), cutoff=5):
    return StatisticalProtocolPlan(
        study_id="SYNTHETIC-001",
        forward=ForwardEvaluationConfig(
            cutoff_session=data.bars[cutoff].session,
            horizons=horizons,
            embargo_bars=1,
            setup=setup_config(),
        ),
        hypotheses=(
            StatisticalHypothesis("H1", "BREAKOUT", horizons[0]),
            StatisticalHypothesis("H2", "RETEST", horizons[-1]),
        ),
    )


def test_plan_validation_fails_closed():
    data = fixture()
    good = plan(data)
    assert len(good.fingerprint()) == 64
    with pytest.raises(ValueError, match="duplicate hypothesis"):
        replace(good, hypotheses=(good.hypotheses[0], good.hypotheses[0]))
    with pytest.raises(ValueError, match="horizon"):
        replace(good, hypotheses=(StatisticalHypothesis("H3", "BREAKOUT", 99),))
    with pytest.raises(ValueError, match="uppercase"):
        StatisticalHypothesis("lowercase", "BREAKOUT", 1)
    with pytest.raises(ValueError, match="positive"):
        StatisticalHypothesis("H3", "BREAKOUT", True)
    with pytest.raises(ValueError, match="event_kind"):
        StatisticalHypothesis("H3", "WRONG", 1)


def test_fingerprint_changes_with_predeclared_cutoff_and_horizon():
    data = fixture()
    a = plan(data)
    assert a.fingerprint() == plan(data).fingerprint()
    assert a.fingerprint() != plan(data, cutoff=6).fingerprint()
    assert a.fingerprint() != plan(data, horizons=(2, 3)).fingerprint()


def test_rows_match_tae003_without_promoting_inference():
    data = fixture()
    specification = plan(data)
    audit = audit_statistical_protocol(data, specification)
    original = evaluate_forward_returns(data, specification.forward)
    assert len(audit.rows) == 4
    assert audit.plan_sha256 == specification.fingerprint()
    assert audit.research_acceptance == "NOT_ESTABLISHED"
    assert audit == audit_statistical_protocol(data, specification)
    for row in audit.rows:
        selected = [
            label
            for label in original.labels
            if label.partition == row.partition
            and label.horizon_bars == row.horizon_bars
            and label.event_kind == row.event_kind
        ]
        matured = [label for label in selected if label.status == "MATURED"]
        assert row.matured_count == len(matured)
        assert row.censored_count == len(selected) - len(matured)
        assert row.inference_status == "NOT_ESTABLISHED"
        assert row.dependency_components <= row.matured_count
        if not matured:
            assert row.mean_directional_return is None
            assert row.directional_positive_fraction is None
    with pytest.raises(FrozenInstanceError):
        audit.rows[0].matured_count = 123


def test_overlapping_windows_and_shared_breakout_clustered():
    data = fixture()
    spec = plan(data)
    matured = [
        label
        for label in evaluate_forward_returns(data, spec.forward).labels
        if label.status == "MATURED"
    ]
    if len(matured) >= 2:
        # Identical labels are an intentionally dependent synthetic pair.
        assert _dependencies([matured[0], matured[0]]) == (1, 1, 1)
        first, second = matured[:2]
        assert _dependencies([first, second])[2] in (1, 2)
    assert _dependencies([]) == (0, 0, 0)


def test_empty_matured_slice_keeps_undefined_means():
    data = fixture()
    spec = plan(data, horizons=(20, 21))
    report = audit_statistical_protocol(data, spec)
    assert all(row.matured_count == 0 for row in report.rows)
    assert all(row.mean_directional_return is None for row in report.rows)
    assert all(row.dependency_components == 0 for row in report.rows)


def test_data_and_plan_are_not_mutated():
    data = fixture()
    spec = plan(data)
    original = data.to_dict()
    audit_statistical_protocol(data, spec)
    assert data.to_dict() == original
    with pytest.raises(TypeError):
        audit_statistical_protocol(data, object())
