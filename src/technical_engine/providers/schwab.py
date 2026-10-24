"""Normalize supplied Schwab daily price-history responses without network I/O."""

from __future__ import annotations

import math
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from technical_engine.data import CorporateAction, OHLCVBar, OHLCVDataset, require_valid_dataset


def normalize_price_history(
    payload: Mapping[str, Any],
    *,
    retrieved_at: datetime,
    available_at: datetime,
    adjustment_policy: str,
    snapshot_id: str,
    session_timezone: str,
    corporate_actions: tuple[CorporateAction, ...] = (),
) -> OHLCVDataset:
    """Normalize daily candles using explicit provenance supplied by the caller.

    ``available_at`` conservatively applies to every value in this supplied
    snapshot. Set it to the actual knowledge time for the adjusted/revised data;
    the candle timestamp does not prove historical availability. The caller
    chooses the exchange timezone and daily endpoint parameters. No timestamp
    rounding, adjustment inference, sorting, aggregation, or gap filling occurs.
    Per-bar action metadata can instead be attached after normalization using
    immutable dataclass replacement when events differ across sessions.
    """
    if not isinstance(payload, Mapping):
        raise ValueError("Schwab response must be an object")
    symbol = payload.get("symbol")
    if not isinstance(symbol, str) or not symbol.strip():
        raise ValueError("Schwab response requires a nonempty symbol")
    candles = payload.get("candles")
    if not isinstance(candles, list):
        raise ValueError("Schwab response requires a candles array")
    zone = ZoneInfo(session_timezone)
    bars = []
    for index, candle in enumerate(candles):
        if not isinstance(candle, Mapping):
            raise ValueError(f"candle {index} must be an object")
        required = {"datetime", "open", "high", "low", "close", "volume"}
        if not required <= set(candle):
            raise ValueError(f"candle {index} is missing required OHLCV fields")
        stamp = candle["datetime"]
        try:
            finite_stamp = isinstance(stamp, (int, float)) and math.isfinite(stamp)
        except OverflowError:
            finite_stamp = False
        if not finite_stamp or isinstance(stamp, bool):
            raise ValueError(f"candle {index} datetime must be finite epoch milliseconds")
        try:
            instant = datetime.fromtimestamp(stamp / 1000, tz=UTC)
        except (ValueError, OverflowError, OSError) as exc:
            raise ValueError(f"candle {index} datetime is out of range") from exc
        bars.append(
            OHLCVBar(
                symbol=symbol,
                session=instant.astimezone(zone).date(),
                open=candle["open"],
                high=candle["high"],
                low=candle["low"],
                close=candle["close"],
                volume=candle["volume"],
                provider="schwab",
                retrieved_at=retrieved_at,
                available_at=available_at,
                adjustment_policy=adjustment_policy,
                snapshot_id=snapshot_id,
                corporate_actions=corporate_actions,
            )
        )
    result = OHLCVDataset(bars=tuple(bars), snapshot_id=snapshot_id)
    require_valid_dataset(result)
    return result
