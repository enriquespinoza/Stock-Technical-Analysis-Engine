"""Synthetic-only TAE-005B context, baseline, and censoring tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest
from test_forward_evaluation import fixture, setup_config

from technical_engine.forward_evaluation import ForwardEvaluationConfig
from technical_engine.indicator_ablation import (
    AblationPlan,
    _context_states,
    audit_indicator_ablations,
)
from technical_engine.indicators import IndicatorConfig
from technical_engine.statistical_protocol import StatisticalHypothesis, StatisticalProtocolPlan


def make_plan(data, horizons=(1, 3)):
    return AblationPlan(
        statistical=StatisticalProtocolPlan(
            "ABLATION_SYNTHETIC",
            ForwardEvaluationConfig(
                cutoff_session=data.bars[5].session,
                horizons=horizons,
                embargo_bars=1,
                setup=setup_config(),
            ),
            (StatisticalHypothesis("H1", "BREAKOUT", horizons[0]),),
        )
    )


def test_context_directional_rules_and_warmup():
    row = {
        "rsi_14": 55.0,
        "ema_9": 105.0,
        "ema_21": 100.0,
        "roc_10": 1.0,
        "macd_histogram_12_26_9": 0.5,
        "atr_14": 3.0,
    }
    assert _context_states(row, 110.0, "UP") == {
        "RSI": True,
        "EMA": True,
        "MOMENTUM": True,
        "ATR": True,
    }
    assert _context_states(row, 110.0, "DOWN") == {
        "RSI": False,
        "EMA": False,
        "MOMENTUM": False,
        "ATR": True,
    }
    assert _context_states({**row, "rsi_14": None}, 110.0, "UP") is None
    with pytest.raises(ValueError, match="invalid numeric"):
        _context_states({**row, "rsi_14": float("nan")}, 110.0, "UP")
    with pytest.raises(ValueError, match="direction"):
        _context_states(row, 110.0, "SIDEWAYS")


def test_fixed_plan_validation_fingerprint_and_immutability():
    data = fixture()
    plan = make_plan(data)
    assert plan.fingerprint() == make_plan(data).fingerprint()
    assert len(plan.fingerprint()) == 64
    with pytest.raises(TypeError):
        replace(plan, statistical=object())
    with pytest.raises(ValueError, match="defaults"):
        replace(plan, indicator=IndicatorConfig(rsi_window=5))
    with pytest.raises(ValueError, match="BREAKOUT"):
        replace(
            plan,
            statistical=replace(
                plan.statistical,
                hypotheses=(StatisticalHypothesis("H2", "RETEST", 1),),
            ),
        )
    with pytest.raises(FrozenInstanceError):
        plan.indicator = IndicatorConfig()


def test_warmup_exclusion_not_treated_as_zero_outcomes():
    data = fixture()
    plan = make_plan(data)
    result = audit_indicator_ablations(data, plan)
    assert result == audit_indicator_ablations(data, plan)
    assert result.research_acceptance == "NOT_ESTABLISHED"
    assert len(result.rows) == 12
    assert {r.treatment for r in result.rows} == {
        "ALL_CONTEXTS",
        "WITHOUT_RSI",
        "WITHOUT_EMA",
        "WITHOUT_MOMENTUM",
        "WITHOUT_ATR",
        "UNFILTERED_ELIGIBLE",
    }
    assert all(r.eligible_count == r.matured_count == r.censored_count == 0 for r in result.rows)
    assert all(r.mean_directional_return is None for r in result.rows)
    assert all(r.descriptive_difference is None for r in result.rows)
    with pytest.raises(TypeError):
        audit_indicator_ablations(data, object())
