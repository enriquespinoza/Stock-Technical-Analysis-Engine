"""Deterministic TAE-004 robustness and suppression tests."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta

import pytest

from technical_engine.data import OHLCVBar, OHLCVDataset
from technical_engine.forward_evaluation import ForwardEvaluationConfig, evaluate_forward_returns
from technical_engine.levels import LevelConfig
from technical_engine.robustness import RobustnessConfig, validate_return_robustness
from technical_engine.setups import SetupConfig
from technical_engine.structure import SwingConfig


def fixture(symbol="TEST", multiplier=1.0):
    high = [12, 20, 16, 21, 22, 22, 22, 23, 24, 24, 25, 26, 25, 27]
    low = [8, 15, 11, 16, 19, 19.8, 17, 19, 20, 20, 21, 22, 20, 22]
    close = [10, 18, 14, 19, 21, 20.5, 18, 21, 22, 23, 24, 25, 21, 26]
    bars = tuple(
        OHLCVBar(
            symbol=symbol,
            session=date(2024, 1, 1) + timedelta(days=i),
            open=c * multiplier,
            high=h * multiplier,
            low=low_value * multiplier,
            close=c * multiplier,
            volume=1000,
            provider="fixture",
            retrieved_at=datetime(2025, 1, 1, tzinfo=UTC),
            available_at=datetime(2024, 1, 1, 22, tzinfo=UTC) + timedelta(days=i),
            adjustment_policy="unadjusted",
            snapshot_id=f"{symbol}-snapshot",
        )
        for i, (h, low_value, c) in enumerate(zip(high, low, close, strict=True))
    )
    return OHLCVDataset(bars, f"{symbol}-snapshot")


def config(**kwargs):
    forward = ForwardEvaluationConfig(
        cutoff_session=date(2024, 1, 5),
        horizons=(1, 2),
        setup=SetupConfig(levels=LevelConfig(swing=SwingConfig(1, 1))),
    )
    return RobustnessConfig(forward, "predeclared-research-fixture", **kwargs)


def test_identical_asset_scaled_benchmark_has_zero_excess_and_is_reproducible():
    asset = fixture()
    benchmark = fixture("BASE", 1.5)
    setting = config(min_clusters=2)
    first = validate_return_robustness(asset, benchmark, setting)
    assert first == validate_return_robustness(asset, benchmark, setting)
    assert len(first.findings) == 6
    assert first.method.endswith("not_independently_validated")
    assert any(f.matured_count > 0 for f in first.findings)
    for finding in first.findings:
        if finding.matured_count:
            assert abs(finding.mean_excess_directional_return) < 1e-14
            assert finding.backfilled_event_count == finding.matured_count
        if finding.status.startswith("SUPPRESSED"):
            assert finding.holm_adjusted_p is None
    with pytest.raises(FrozenInstanceError):
        first.findings[0].matured_count = 999


def test_small_sample_suppresses_inference_but_preserves_counts():
    report = validate_return_robustness(fixture(), fixture("BASE"), config())
    assert all(f.status == "SUPPRESSED_INSUFFICIENT_CLUSTERS" for f in report.findings)
    assert all(f.bootstrap_lower is None for f in report.findings)
    assert all(f.sign_flip_p is None for f in report.findings)


def test_benchmark_alignment_and_identity_fail_closed():
    asset = fixture()
    benchmark = fixture("BASE")
    with pytest.raises(ValueError, match="different symbol"):
        validate_return_robustness(asset, asset, config())
    altered = replace(benchmark, bars=benchmark.bars[1:])
    with pytest.raises(ValueError, match="sessions"):
        validate_return_robustness(asset, altered, config())
    mismatched = replace(
        benchmark,
        bars=tuple(replace(bar, adjustment_policy="adjusted") for bar in benchmark.bars),
    )
    with pytest.raises(ValueError, match="adjustment policies"):
        validate_return_robustness(asset, mismatched, config())


def test_reject_forged_evaluation_and_invalid_config():
    asset = fixture()
    benchmark = fixture("BASE")
    setting = config()
    evaluation = evaluate_forward_returns(asset, setting.forward)
    corrupted = replace(evaluation, snapshot_id="other")
    with pytest.raises(ValueError, match="recomputed"):
        validate_return_robustness(asset, benchmark, setting, evaluation=corrupted)
    with pytest.raises(TypeError):
        validate_return_robustness(asset, benchmark, object())
    for params in (
        {"analysis_label": " "},
        {"seed": True},
        {"resamples": 10},
        {"min_clusters": 1},
        {"largest_cluster_limit": 0},
        {"largest_cluster_limit": 2},
        {"interval_level": float("nan")},
        {"interval_level": 1},
    ):
        base = {"forward": setting.forward, "analysis_label": "test"}
        base.update(params)
        with pytest.raises((ValueError, TypeError)):
            RobustnessConfig(**base)
