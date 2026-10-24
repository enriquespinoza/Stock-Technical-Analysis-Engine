"""Causal, descriptive swing-point research.

A pivot at position ``i`` requires ``right`` subsequent observations. The pivot
is never labelled as confirmed until the right-side confirmation bar exists.
This module does not predict returns or authorize trading.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from technical_engine.data import OHLCVDataset, require_valid_dataset

SwingKind = Literal["HIGH", "LOW"]


@dataclass(frozen=True)
class SwingConfig:
    left: int = 2
    right: int = 2
    tolerance_bps: float = 0.0

    def __post_init__(self) -> None:
        for name in ("left", "right"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if (
            isinstance(self.tolerance_bps, bool)
            or not isinstance(self.tolerance_bps, (int, float))
            or not math.isfinite(self.tolerance_bps)
            or self.tolerance_bps < 0
        ):
            raise ValueError("tolerance_bps must be finite and nonnegative")


@dataclass(frozen=True)
class ConfirmedSwing:
    kind: SwingKind
    pivot_index: int
    confirmation_index: int
    pivot_session: date
    confirmation_session: date
    price: float
    available_at: datetime
    retrieved_at: datetime
    usable_at: datetime
    snapshot_id: str


def confirmed_swings(
    dataset: OHLCVDataset, config: SwingConfig | None = None
) -> tuple[ConfirmedSwing, ...]:
    """Return confirmed swings using only observations through their confirmation bar.

    A HIGH requires a strictly higher high than every neighboring high, after a
    tolerance proportional to the pivot price. LOW is symmetrical. Ties do not
    confirm. ``usable_at`` is conservative: it includes the latest source
    availability AND retrieval timestamp from the required input prefix. A
    modern backfill must not be misrepresented as a signal issued in the past.
    """
    require_valid_dataset(dataset)
    config = SwingConfig() if config is None else config
    if not isinstance(config, SwingConfig):
        raise TypeError("config must be a SwingConfig")
    bars = dataset.bars
    if len(bars) < config.left + config.right + 1:
        return ()

    result: list[ConfirmedSwing] = []
    for i in range(config.left, len(bars) - config.right):
        pivot = bars[i]
        neighbors = [
            bars[j]
            for j in range(i - config.left, i + config.right + 1)
            if j != i
        ]
        high_margin = pivot.high * config.tolerance_bps / 10_000.0
        low_margin = pivot.low * config.tolerance_bps / 10_000.0
        high = all(pivot.high > other.high + high_margin for other in neighbors)
        low = all(pivot.low < other.low - low_margin for other in neighbors)
        if not (high or low):
            continue
        confirmation_index = i + config.right
        observed = bars[: confirmation_index + 1]
        available_at = max(bar.available_at for bar in observed)
        retrieved_at = max(bar.retrieved_at for bar in observed)
        for kind, price in (("HIGH", pivot.high), ("LOW", pivot.low)):
            if (kind == "HIGH" and high) or (kind == "LOW" and low):
                result.append(
                    ConfirmedSwing(
                        kind=kind,
                        pivot_index=i,
                        confirmation_index=confirmation_index,
                        pivot_session=pivot.session,
                        confirmation_session=bars[confirmation_index].session,
                        price=price,
                        available_at=available_at,
                        retrieved_at=retrieved_at,
                        usable_at=max(available_at, retrieved_at),
                        snapshot_id=dataset.snapshot_id,
                    )
                )
    return tuple(result)
