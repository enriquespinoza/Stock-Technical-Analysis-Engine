"""Deterministic, trailing technical features without external data access.

Prices are never rounded and inputs are never filled, reordered, or mutated.
Unavailable warm-up values are ``None``, not NaN. Feature availability is the
maximum bar availability over the consumed input prefix, including revisions;
breakout and volume baselines exclude the current bar. See :func:`feature_metadata`
for exact formula conventions.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, fields
from math import fsum, isfinite, log, sqrt
from typing import Any

from technical_engine.data import OHLCVDataset, require_valid_dataset

CONFIG_VERSION = "1.0.0"


@dataclass(frozen=True)
class IndicatorConfig:
    """Versioned feature parameters; sequence inputs are defensively copied."""

    version: str = CONFIG_VERSION
    sma_windows: tuple[int, ...] = (20, 50, 200)
    ema_windows: tuple[int, ...] = (9, 21, 50)
    rsi_window: int = 14
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    atr_window: int = 14
    volatility_window: int = 20
    annualization: float = 252.0
    roc_windows: tuple[int, ...] = (5, 10, 20)
    relative_volume_window: int = 20
    breakout_window: int = 20

    def __post_init__(self) -> None:
        if self.version != CONFIG_VERSION:
            raise ValueError(f"Unsupported indicator configuration version: {self.version!r}")
        for name in ("sma_windows", "ema_windows", "roc_windows"):
            values = getattr(self, name)
            if not isinstance(values, (tuple, list)) or not values:
                raise ValueError(f"{name} must be a nonempty sequence of positive integers")
            values = tuple(values)
            for value in values:
                _require_period(value, name)
            if len(set(values)) != len(values):
                raise ValueError(f"{name} cannot contain duplicate periods")
            object.__setattr__(self, name, values)
        for name in (
            "rsi_window",
            "macd_fast",
            "macd_slow",
            "macd_signal",
            "atr_window",
            "volatility_window",
            "relative_volume_window",
            "breakout_window",
        ):
            _require_period(getattr(self, name), name)
        if self.macd_fast >= self.macd_slow:
            raise ValueError("macd_fast must be smaller than macd_slow")
        if self.volatility_window < 2:
            raise ValueError("volatility_window must be at least 2 for sample variance")
        try:
            annualization = float(self.annualization)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError("annualization must be a finite positive number") from error
        if (
            isinstance(self.annualization, bool)
            or not isinstance(self.annualization, (int, float))
            or not isfinite(annualization)
            or annualization <= 0
        ):
            raise ValueError("annualization must be a finite positive number")
        object.__setattr__(self, "annualization", annualization)

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-safe parameters without exposing mutable config state."""
        result = asdict(self)
        for name in ("sma_windows", "ema_windows", "roc_windows"):
            result[name] = list(result[name])
        return result

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> IndicatorConfig:
        if not isinstance(value, Mapping):
            raise ValueError("Indicator configuration must be an object")
        unknown = set(value) - {field.name for field in fields(cls)}
        if unknown:
            raise ValueError(f"Unknown indicator configuration fields: {sorted(unknown)!r}")
        return cls(**dict(value))


def _require_period(value: Any, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must contain positive integer periods")


def _mean(values: Sequence[float]) -> float:
    # Scale before summation to avoid overflowing a sum of finite prices.
    return fsum(value / len(values) for value in values)


def _sma(values: Sequence[float], window: int) -> list[float | None]:
    return [
        _mean(values[index - window + 1 : index + 1]) if index >= window - 1 else None
        for index in range(len(values))
    ]


def _ema(values: Sequence[float], window: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    if len(values) < window:
        return result
    previous = _mean(values[:window])
    result[window - 1] = previous
    alpha = 2.0 / (window + 1)
    for index in range(window, len(values)):
        previous = alpha * values[index] + (1.0 - alpha) * previous
        result[index] = previous
    return result


def _wilder(values: Sequence[float], window: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    if len(values) < window:
        return result
    previous = _mean(values[:window])
    result[window - 1] = previous
    for index in range(window, len(values)):
        previous = previous * ((window - 1.0) / window) + values[index] / window
        result[index] = previous
    return result


def _rsi(closes: Sequence[float], window: int) -> list[float | None]:
    changes = [current - previous for previous, current in zip(closes, closes[1:], strict=False)]
    gains = _wilder([max(change, 0.0) for change in changes], window)
    losses = _wilder([max(-change, 0.0) for change in changes], window)
    result: list[float | None] = [None]
    for gain, loss in zip(gains, losses, strict=True):
        if gain is None or loss is None:
            result.append(None)
        elif gain == 0 and loss == 0:
            result.append(50.0)
        elif loss == 0:
            result.append(100.0)
        elif gain > loss:
            result.append(100.0 / (1.0 + loss / gain))
        else:
            ratio = gain / loss
            result.append(100.0 * ratio / (1.0 + ratio))
    return result[: len(closes)]


def compute_features(
    dataset: OHLCVDataset,
    config: IndicatorConfig | None = None,
) -> list[dict[str, Any]]:
    """Return one row per validated bar, retaining all warm-up rows.

    A short, otherwise valid history is accepted: features with insufficient
    lookback remain ``None``. Invalid, unsorted, duplicate, or missing data is
    rejected by the OHLCV contract instead of being silently repaired.
    """
    config = config if config is not None else IndicatorConfig()
    if not isinstance(config, IndicatorConfig):
        raise ValueError("config must be an IndicatorConfig")
    require_valid_dataset(dataset, min_history=1)
    bars = dataset.bars
    closes = [float(bar.close) for bar in bars]
    highs = [float(bar.high) for bar in bars]
    lows = [float(bar.low) for bar in bars]
    volumes = [float(bar.volume) for bar in bars]
    rows: list[dict[str, Any]] = [
        {"symbol": bar.symbol, "session": bar.session.isoformat()} for bar in bars
    ]

    def assign(name: str, values: Sequence[float | None]) -> None:
        for row, value in zip(rows, values, strict=True):
            if value is not None and not isfinite(value):
                raise ValueError(f"{name} cannot be represented as a finite float")
            row[name] = value

    for window in config.sma_windows:
        assign(f"sma_{window}", _sma(closes, window))
    for window in config.ema_windows:
        assign(f"ema_{window}", _ema(closes, window))
    assign(f"rsi_{config.rsi_window}", _rsi(closes, config.rsi_window))

    fast = _ema(closes, config.macd_fast)
    slow = _ema(closes, config.macd_slow)
    macd = [
        fast_value - slow_value if fast_value is not None and slow_value is not None else None
        for fast_value, slow_value in zip(fast, slow, strict=True)
    ]
    offset = config.macd_slow - 1
    valid_macd = [value for value in macd[offset:] if value is not None]
    signal = ([None] * min(offset, len(bars))) + _ema(valid_macd, config.macd_signal)
    histogram = [
        value - signal_value if value is not None and signal_value is not None else None
        for value, signal_value in zip(macd, signal, strict=True)
    ]
    assign(f"macd_{config.macd_fast}_{config.macd_slow}", macd)
    assign(f"macd_signal_{config.macd_signal}", signal)
    assign(
        f"macd_histogram_{config.macd_fast}_{config.macd_slow}_{config.macd_signal}",
        histogram,
    )

    true_ranges = [highs[0] - lows[0]]
    true_ranges.extend(
        max(
            highs[index] - lows[index],
            abs(highs[index] - closes[index - 1]),
            abs(lows[index] - closes[index - 1]),
        )
        for index in range(1, len(bars))
    )
    assign(f"atr_{config.atr_window}", _wilder(true_ranges, config.atr_window))

    returns = [
        log(current) - log(previous) for previous, current in zip(closes, closes[1:], strict=False)
    ]
    volatility: list[float | None] = [None] * len(bars)
    for index in range(config.volatility_window, len(bars)):
        window_returns = returns[index - config.volatility_window : index]
        mean = _mean(window_returns)
        variance = fsum((value - mean) ** 2 for value in window_returns) / (
            config.volatility_window - 1
        )
        volatility[index] = sqrt(variance) * sqrt(config.annualization)
    assign(f"realized_volatility_{config.volatility_window}", volatility)

    for window in config.roc_windows:
        assign(
            f"roc_{window}",
            [
                100.0 * (close / closes[index - window] - 1.0) if index >= window else None
                for index, close in enumerate(closes)
            ],
        )

    relative_volume: list[float | None] = [None] * len(bars)
    for index in range(config.relative_volume_window, len(bars)):
        baseline = _mean(volumes[index - config.relative_volume_window : index])
        relative_volume[index] = volumes[index] / baseline if baseline > 0 else None
    assign(f"relative_volume_{config.relative_volume_window}", relative_volume)

    window = config.breakout_window
    assign(
        f"prior_high_{window}",
        [
            max(highs[index - window : index]) if index >= window else None
            for index in range(len(bars))
        ],
    )
    assign(
        f"prior_low_{window}",
        [
            min(lows[index - window : index]) if index >= window else None
            for index in range(len(bars))
        ],
    )
    return rows


def feature_metadata(config: IndicatorConfig | None = None) -> dict[str, Any]:
    """Return formulas and exact first-valid-row lookbacks for every feature."""
    config = config if config is not None else IndicatorConfig()
    if not isinstance(config, IndicatorConfig):
        raise ValueError("config must be an IndicatorConfig")
    features: dict[str, dict[str, Any]] = {}

    def add(
        name: str,
        formula: str,
        window: int,
        minimum_bars: int,
        units: str,
        baseline: str = "through_current_session",
    ) -> None:
        features[name] = {
            "formula": formula,
            "window_sessions": window,
            "minimum_bars": minimum_bars,
            "warmup_rows": minimum_bars - 1,
            "units": units,
            "input_scope": baseline,
            "available_at": "feature_available_at = max(bar.available_at over input prefix)",
            "missing_value": None,
        }

    for window in config.sma_windows:
        add(
            f"sma_{window}",
            "arithmetic mean of trailing closes including current",
            window,
            window,
            "price",
        )
    for window in config.ema_windows:
        add(
            f"ema_{window}",
            "SMA seed; EMA_t = (2/(n+1))*close_t + (1-2/(n+1))*EMA_(t-1)",
            window,
            window,
            "price",
        )
    add(
        f"rsi_{config.rsi_window}",
        "Wilder arithmetic gain/loss seeds over n changes, then alpha=1/n; "
        "100*avg_gain/(avg_gain+avg_loss); flat=50, loss-free=100, gain-free=0",
        config.rsi_window,
        config.rsi_window + 1,
        "index_0_to_100",
    )
    add(
        f"macd_{config.macd_fast}_{config.macd_slow}",
        "SMA-seeded EMA_fast(close) - SMA-seeded EMA_slow(close)",
        config.macd_slow,
        config.macd_slow,
        "price",
    )
    signal_minimum = config.macd_slow + config.macd_signal - 1
    add(
        f"macd_signal_{config.macd_signal}",
        "SMA-seeded EMA_signal of valid MACD values",
        config.macd_signal,
        signal_minimum,
        "price",
    )
    add(
        f"macd_histogram_{config.macd_fast}_{config.macd_slow}_{config.macd_signal}",
        "MACD - signal",
        config.macd_signal,
        signal_minimum,
        "price",
    )
    add(
        f"atr_{config.atr_window}",
        "TR_0=high-low; subsequent TR=max(high-low,abs(high-prev_close),"
        "abs(low-prev_close)); first n TR arithmetic seed, then Wilder alpha=1/n",
        config.atr_window,
        config.atr_window,
        "price",
    )
    add(
        f"realized_volatility_{config.volatility_window}",
        "sample standard deviation (ddof=1) of trailing n log(close_t/close_(t-1)) "
        "returns times sqrt(annualization)",
        config.volatility_window,
        config.volatility_window + 1,
        "annualized_return_fraction",
    )
    for window in config.roc_windows:
        add(f"roc_{window}", "100*(close_t/close_(t-n)-1)", window, window + 1, "percent")
    add(
        f"relative_volume_{config.relative_volume_window}",
        "current volume / mean of strictly prior n volumes; zero baseline yields null",
        config.relative_volume_window,
        config.relative_volume_window + 1,
        "ratio",
        "current_volume_divided_by_strictly_prior_baseline",
    )
    add(
        f"prior_high_{config.breakout_window}",
        "maximum of strictly prior n highs",
        config.breakout_window,
        config.breakout_window + 1,
        "price",
        "strictly_prior_sessions",
    )
    add(
        f"prior_low_{config.breakout_window}",
        "minimum of strictly prior n lows",
        config.breakout_window,
        config.breakout_window + 1,
        "price",
        "strictly_prior_sessions",
    )
    return {
        "config_version": config.version,
        "configuration": config.to_dict(),
        "numeric_type": "IEEE-754 binary64; no rounding",
        "ordering": "one feature row per input bar; input order is validated",
        "warmup": "retain rows with JSON null until each individual lookback is available",
        "availability": "end-of-session research features, usable no earlier than feature_available_at "
        "(maximum bar.available_at over input prefix, including revisions)",
        "features": features,
    }
