"""Independent references and temporal invariants for the indicator contract."""

from __future__ import annotations

import copy
import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext
from math import cos, log, sin, sqrt
from statistics import mean, stdev

import pytest

from technical_engine.data import OHLCVBar, OHLCVDataset
from technical_engine.indicators import IndicatorConfig, compute_features, feature_metadata


def dataset(
    closes: list[float] | None = None,
    volumes: list[float] | None = None,
) -> OHLCVDataset:
    closes = (
        closes
        if closes is not None
        else [
            100 + index * 0.07 + 3 * sin(index * 0.31) + cos(index * 0.11) for index in range(260)
        ]
    )
    volumes = volumes if volumes is not None else [1000 + index * 7 for index in range(len(closes))]
    bars = tuple(
        OHLCVBar(
            symbol="TEST",
            session=date(2023, 1, 1) + timedelta(days=index),
            open=close + 0.2,
            high=close + 1.5,
            low=close - 1.25,
            close=close,
            volume=volumes[index],
            provider="fixture",
            retrieved_at=datetime(2025, 1, 1, tzinfo=UTC),
            available_at=datetime(2023, 1, 1, 21, tzinfo=UTC) + timedelta(days=index),
            adjustment_policy="unadjusted",
            snapshot_id="indicator-fixture-v1",
        )
        for index, close in enumerate(closes)
    )
    return OHLCVDataset(bars=bars, snapshot_id="indicator-fixture-v1")


def small_config(**overrides: object) -> IndicatorConfig:
    values = {
        "sma_windows": (2,),
        "ema_windows": (2,),
        "rsi_window": 2,
        "macd_fast": 2,
        "macd_slow": 3,
        "macd_signal": 2,
        "atr_window": 2,
        "volatility_window": 2,
        "roc_windows": (1,),
        "relative_volume_window": 2,
        "breakout_window": 2,
    }
    values.update(overrides)
    return IndicatorConfig(**values)


def weighted_reference(
    values: list[float], window: int, wilder: bool = False
) -> list[float | None]:
    """High-precision closed-form exponential weights, not iterative smoothing."""
    result: list[float | None] = [None] * len(values)
    with localcontext() as context:
        context.prec = 50
        numbers = [Decimal(str(value)) for value in values]
        alpha = Decimal(1) / window if wilder else Decimal(2) / (window + 1)
        decay = 1 - alpha
        seed = sum(numbers[:window]) / window
        for index in range(window - 1, len(values)):
            power = index - window + 1
            total = seed * decay**power
            total += sum(
                alpha * decay ** (index - position) * numbers[position]
                for position in range(window, index + 1)
            )
            result[index] = float(total)
    return result


def assert_series(rows: list[dict], column: str, expected: list[float | None]) -> None:
    assert len(rows) == len(expected)
    for row, reference in zip(rows, expected, strict=True):
        if reference is None:
            assert row[column] is None
        else:
            assert row[column] == pytest.approx(reference, rel=2e-12, abs=2e-12)


def test_all_default_indicators_against_independent_references() -> None:
    source = dataset()
    rows = compute_features(source)
    closes = [bar.close for bar in source.bars]
    for window in (20, 50, 200):
        expected = [
            mean(closes[index - window + 1 : index + 1]) if index >= window - 1 else None
            for index in range(len(closes))
        ]
        assert_series(rows, f"sma_{window}", expected)
    for window in (9, 21, 50):
        assert_series(rows, f"ema_{window}", weighted_reference(closes, window))

    changes = [closes[index] - closes[index - 1] for index in range(1, len(closes))]
    gains = weighted_reference([max(value, 0) for value in changes], 14, wilder=True)
    losses = weighted_reference([max(-value, 0) for value in changes], 14, wilder=True)
    rsi: list[float | None] = [None]
    for gain, loss in zip(gains, losses, strict=True):
        rsi.append(None if gain is None else 100 - 100 / (1 + gain / loss))
    assert_series(rows, "rsi_14", rsi)

    fast = weighted_reference(closes, 12)
    slow = weighted_reference(closes, 26)
    macd = [None if b is None else a - b for a, b in zip(fast, slow, strict=True)]
    signal = [None] * 25 + weighted_reference(macd[25:], 9)
    histogram = [None if b is None else a - b for a, b in zip(macd, signal, strict=True)]
    assert_series(rows, "macd_12_26", macd)
    assert_series(rows, "macd_signal_9", signal)
    assert_series(rows, "macd_histogram_12_26_9", histogram)

    ranges = [source.bars[0].high - source.bars[0].low]
    for previous, current in zip(source.bars, source.bars[1:], strict=False):
        ranges.append(max(current.high, previous.close) - min(current.low, previous.close))
    assert_series(rows, "atr_14", weighted_reference(ranges, 14, wilder=True))

    returns = [log(b / a) for a, b in zip(closes, closes[1:], strict=False)]
    expected_volatility = [None] * 20 + [
        stdev(returns[index - 20 : index]) * sqrt(252) for index in range(20, len(closes))
    ]
    assert_series(rows, "realized_volatility_20", expected_volatility)
    for window in (5, 10, 20):
        expected_roc = [None] * window + [
            (closes[index] - closes[index - window]) / closes[index - window] * 100
            for index in range(window, len(closes))
        ]
        assert_series(rows, f"roc_{window}", expected_roc)
    for index, row in enumerate(rows):
        if index < 20:
            assert row["relative_volume_20"] is None
            assert row["prior_high_20"] is None
            assert row["prior_low_20"] is None
        else:
            previous = source.bars[index - 20 : index]
            assert row["relative_volume_20"] == pytest.approx(
                source.bars[index].volume / mean(bar.volume for bar in previous)
            )
            assert row["prior_high_20"] == max(bar.high for bar in previous)
            assert row["prior_low_20"] == min(bar.low for bar in previous)


def test_wilder_rsi_matches_published_hand_calculation_seed() -> None:
    closes = [
        44.34,
        44.09,
        44.15,
        43.61,
        44.33,
        44.83,
        45.10,
        45.42,
        45.84,
        46.08,
        45.89,
        46.03,
        45.61,
        46.28,
        46.28,
        46.00,
        46.03,
        46.41,
        46.22,
        45.64,
        46.21,
    ]
    rows = compute_features(dataset(closes))
    assert rows[13]["rsi_14"] is None
    assert rows[14]["rsi_14"] == pytest.approx(70.46413502109705)
    assert rows[15]["rsi_14"] == pytest.approx(66.24961855355505)
    assert rows[20]["rsi_14"] == pytest.approx(62.880718309962404)


def test_all_warmups_match_metadata_and_full_default_coverage() -> None:
    config = IndicatorConfig()
    rows = compute_features(dataset(), config)
    metadata = feature_metadata(config)
    assert set(rows[0]) - {"symbol", "session"} == set(metadata["features"])
    for column, info in metadata["features"].items():
        first = info["minimum_bars"] - 1
        assert all(row[column] is None for row in rows[:first])
        assert rows[first][column] is not None
        assert info["warmup_rows"] == first
    assert rows[198]["sma_200"] is None
    assert rows[199]["sma_200"] is not None
    assert rows[32]["macd_signal_9"] is None
    assert rows[33]["macd_signal_9"] is not None


@pytest.mark.parametrize("length", [1, 2, 8, 14, 19])
def test_short_history_retained_without_fabricated_features(length: int) -> None:
    rows = compute_features(dataset([100.0] * length))
    assert len(rows) == length
    assert all(row["sma_200"] is None for row in rows)
    assert all(row["realized_volatility_20"] is None for row in rows)
    assert all(row["macd_signal_9"] is None for row in rows)
    assert rows[0]["session"] == "2023-01-01"


@pytest.mark.parametrize(
    "closes,expected",
    [
        ([100.0] * 10, 50.0),
        ([100.0 + index for index in range(10)], 100.0),
        ([100.0 - index for index in range(10)], 0.0),
    ],
)
def test_rsi_flat_gain_only_and_loss_only(closes: list[float], expected: float) -> None:
    rows = compute_features(dataset(closes), small_config())
    assert all(row["rsi_2"] == expected for row in rows[2:])


def test_zero_volume_is_valid_and_zero_baseline_returns_null() -> None:
    rows = compute_features(dataset([100.0] * 6, [0.0, 0.0, 300.0, 0.0, 0.0, 0.0]), small_config())
    assert rows[2]["relative_volume_2"] is None
    assert rows[3]["relative_volume_2"] == 0.0
    assert rows[4]["relative_volume_2"] == 0.0
    assert rows[5]["relative_volume_2"] is None
    assert rows[-1]["realized_volatility_2"] == 0.0


def test_prior_high_low_and_relative_volume_exclude_current_bar() -> None:
    source = dataset([100.0, 101.0, 500.0], [100.0, 200.0, 30000.0])
    rows = compute_features(source, small_config())
    assert rows[2]["prior_high_2"] == 102.5
    assert rows[2]["prior_low_2"] == 98.75
    assert rows[2]["relative_volume_2"] == 200.0
    modified = replace(
        source,
        bars=source.bars[:2]
        + (
            replace(
                source.bars[2], open=600.2, high=601.5, low=598.75, close=600.0, volume=60000.0
            ),
        ),
    )
    changed = compute_features(modified, small_config())
    assert rows[:2] == changed[:2]
    assert changed[2]["prior_high_2"] == rows[2]["prior_high_2"]
    assert changed[2]["prior_low_2"] == rows[2]["prior_low_2"]
    assert changed[2]["relative_volume_2"] == 400.0


def test_atr_uses_gap_from_previous_close_and_wilder_smoothing() -> None:
    rows = compute_features(dataset([100.0, 110.0, 105.0]), small_config())
    # TRs are 2.75, 11.5 (gap up), and 6.25 (gap down).
    assert rows[0]["atr_2"] is None
    assert rows[1]["atr_2"] == 7.125
    assert rows[2]["atr_2"] == 6.6875


def test_single_session_windows_preserve_exact_observation_and_warmup() -> None:
    config = small_config(
        sma_windows=(1,),
        ema_windows=(1,),
        rsi_window=1,
        macd_fast=1,
        macd_slow=2,
        macd_signal=1,
        atr_window=1,
    )
    rows = compute_features(dataset([100.0, 110.0, 105.0]), config)
    assert [row["sma_1"] for row in rows] == [100.0, 110.0, 105.0]
    assert [row["ema_1"] for row in rows] == [100.0, 110.0, 105.0]
    assert [row["atr_1"] for row in rows] == [2.75, 11.5, 6.25]
    assert [row["rsi_1"] for row in rows] == [None, 100.0, 0.0]
    assert rows[0]["macd_signal_1"] is None
    assert rows[1]["macd_histogram_1_2_1"] == 0.0


def test_future_append_invariance_for_every_prefix_and_feature() -> None:
    source = dataset()
    full = compute_features(source)
    for length in (1, 8, 14, 20, 21, 26, 33, 34, 50, 199, 200, 220):
        prefix = replace(source, bars=source.bars[:length])
        assert compute_features(prefix) == full[:length]


def test_determinism_serialization_and_no_input_mutation() -> None:
    source = dataset()
    before = copy.deepcopy(source)
    config = IndicatorConfig()
    original_parameters = config.to_dict()
    first = compute_features(source, config)
    assert source == before
    assert config.to_dict() == original_parameters
    assert json.dumps(first, sort_keys=True, allow_nan=False) == json.dumps(
        compute_features(source, config),
        sort_keys=True,
        allow_nan=False,
    )


@pytest.mark.parametrize("kind", ["reversed", "duplicate", "nan", "missing", "negative_volume"])
def test_invalid_data_is_rejected_not_silently_repaired(kind: str) -> None:
    source = dataset([100.0, 101.0, 102.0])
    if kind == "reversed":
        source = replace(source, bars=tuple(reversed(source.bars)))
    elif kind == "duplicate":
        source = replace(source, bars=(source.bars[0], source.bars[0], source.bars[2]))
    else:
        values = {
            "nan": {"close": float("nan")},
            "missing": {"close": None},
            "negative_volume": {"volume": -1.0},
        }
        source = replace(source, bars=(replace(source.bars[0], **values[kind]),) + source.bars[1:])
    with pytest.raises(ValueError):
        compute_features(source)


def test_empty_data_rejected() -> None:
    with pytest.raises(ValueError):
        compute_features(OHLCVDataset(bars=(), snapshot_id="indicator-fixture-v1"))


@pytest.mark.parametrize(
    "parameters",
    [
        {"sma_windows": ()},
        {"sma_windows": (20, 20)},
        {"sma_windows": (True,)},
        {"ema_windows": (0,)},
        {"roc_windows": (1.5,)},
        {"rsi_window": False},
        {"rsi_window": 0},
        {"atr_window": -1},
        {"volatility_window": 1},
        {"macd_fast": 26},
        {"macd_signal": 0},
        {"annualization": float("inf")},
        {"annualization": float("nan")},
        {"annualization": 0},
        {"annualization": True},
        {"annualization": 10**400},
        {"relative_volume_window": -1},
        {"breakout_window": 2.0},
        {"version": "unknown"},
    ],
)
def test_invalid_configuration_fails_explicitly(parameters: dict) -> None:
    with pytest.raises(ValueError):
        IndicatorConfig(**parameters)


def test_config_defensive_copy_immutability_and_json_roundtrip() -> None:
    windows = [2, 3]
    config = small_config(sma_windows=windows)
    windows.append(4)
    assert config.sma_windows == (2, 3)
    exported = config.to_dict()
    exported["sma_windows"].append(5)
    assert config.sma_windows == (2, 3)
    with pytest.raises(FrozenInstanceError):
        config.rsi_window = 3
    assert IndicatorConfig.from_dict(json.loads(json.dumps(config.to_dict()))) == config
    with pytest.raises(ValueError, match="Unknown"):
        IndicatorConfig.from_dict({"typo_window": 10})


def test_custom_annualization_changes_only_realized_volatility_scale() -> None:
    source = dataset([100.0, 101.0, 99.0, 105.0])
    a = compute_features(source, small_config(annualization=1))
    b = compute_features(source, small_config(annualization=4))
    assert b[-1]["realized_volatility_2"] == pytest.approx(2 * a[-1]["realized_volatility_2"])
    assert {key: value for key, value in a[-1].items() if key != "realized_volatility_2"} == {
        key: value for key, value in b[-1].items() if key != "realized_volatility_2"
    }


def test_metadata_records_asof_prior_baseline_and_every_config_parameter() -> None:
    config = small_config()
    metadata = feature_metadata(config)
    assert metadata["configuration"] == config.to_dict()
    assert "maximum bar.available_at over input prefix" in metadata["availability"]
    assert metadata["features"]["prior_high_2"]["input_scope"] == "strictly_prior_sessions"
    assert "strictly_prior_baseline" in metadata["features"]["relative_volume_2"]["input_scope"]
    assert "Wilder" in metadata["features"]["rsi_2"]["formula"]
    assert "ddof=1" in metadata["features"]["realized_volatility_2"]["formula"]
    json.dumps(metadata, sort_keys=True, allow_nan=False)
