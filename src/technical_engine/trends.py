"""Causal, descriptive market-structure trend classifications.

States update only when TAE-002A swings become confirmed. In particular, a
later-confirmed pivot does not change the trend history at its pivot session.
This research module makes no return, trading, or execution claims.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal

from technical_engine.data import OHLCVDataset
from technical_engine.structure import ConfirmedSwing, SwingConfig, SwingKind, confirmed_swings

HighStructure = Literal["HH", "LH", "EH"]
LowStructure = Literal["HL", "LL", "EL"]
TrendState = Literal["UPTREND", "DOWNTREND", "SIDEWAYS", "INDETERMINATE"]


@dataclass(frozen=True)
class TrendConfig:
    swing: SwingConfig = field(default_factory=SwingConfig)
    comparison_tolerance_bps: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.swing, SwingConfig):
            raise TypeError("swing must be a SwingConfig")
        tolerance = self.comparison_tolerance_bps
        if (
            isinstance(tolerance, bool)
            or not isinstance(tolerance, (int, float))
            or not math.isfinite(tolerance)
            or tolerance < 0
        ):
            raise ValueError("comparison_tolerance_bps must be finite and nonnegative")


@dataclass(frozen=True)
class TrendEvent:
    """Frozen classification immediately after one confirmed swing event.

    The event is attached to the *confirmation* session, never backdated to
    the pivot. ``usable_at`` additionally enforces data availability and
    retrieval knowledge time for historical backfills.
    """

    event_index: int
    state: TrendState
    swing_kind: SwingKind
    pivot_index: int
    confirmation_index: int
    pivot_session: date
    confirmation_session: date
    swing_price: float
    high_structure: HighStructure | None
    low_structure: LowStructure | None
    latest_high_price: float | None
    latest_low_price: float | None
    latest_high_pivot_index: int | None
    latest_low_pivot_index: int | None
    available_at: datetime
    retrieved_at: datetime
    usable_at: datetime
    snapshot_id: str


def _compare(current: float, previous: float, tolerance_bps: float) -> int:
    """Compare two same-kind pivot prices against the *previous* price."""
    margin = previous * tolerance_bps / 10_000.0
    if current > previous + margin:
        return 1
    if current < previous - margin:
        return -1
    return 0


def _classify(high: HighStructure | None, low: LowStructure | None) -> TrendState:
    if high is None or low is None:
        return "INDETERMINATE"
    if high == "HH" and low == "HL":
        return "UPTREND"
    if high == "LH" and low == "LL":
        return "DOWNTREND"
    return "SIDEWAYS"


def trend_events(
    dataset: OHLCVDataset, config: TrendConfig | None = None
) -> tuple[TrendEvent, ...]:
    """Build a deterministic, append-only trend ledger from confirmed swings.

    Two confirmed HIGH pivots and two confirmed LOW pivots are required before
    classifying a trend. HH+HL -> uptrend; LH+LL -> downtrend; all other
    fully-observed combinations (including equal extrema) -> sideways.
    Earlier events never change when later observations arrive.

    Source data is validated by ``confirmed_swings``. Events are scoped to
    the dataset snapshot; cross-snapshot reconciliation is out of scope.
    """
    config = TrendConfig() if config is None else config
    if not isinstance(config, TrendConfig):
        raise TypeError("config must be a TrendConfig")

    events: list[TrendEvent] = []
    latest_high: ConfirmedSwing | None = None
    latest_low: ConfirmedSwing | None = None
    high_structure: HighStructure | None = None
    low_structure: LowStructure | None = None

    for swing in confirmed_swings(dataset, config.swing):
        if swing.kind == "HIGH":
            if latest_high is not None:
                comparison = _compare(
                    swing.price, latest_high.price, config.comparison_tolerance_bps
                )
                high_structure = {1: "HH", -1: "LH", 0: "EH"}[comparison]
            latest_high = swing
        else:
            if latest_low is not None:
                comparison = _compare(
                    swing.price, latest_low.price, config.comparison_tolerance_bps
                )
                low_structure = {1: "HL", -1: "LL", 0: "EL"}[comparison]
            latest_low = swing

        events.append(
            TrendEvent(
                event_index=len(events),
                state=_classify(high_structure, low_structure),
                swing_kind=swing.kind,
                pivot_index=swing.pivot_index,
                confirmation_index=swing.confirmation_index,
                pivot_session=swing.pivot_session,
                confirmation_session=swing.confirmation_session,
                swing_price=swing.price,
                high_structure=high_structure,
                low_structure=low_structure,
                latest_high_price=latest_high.price if latest_high is not None else None,
                latest_low_price=latest_low.price if latest_low is not None else None,
                latest_high_pivot_index=(
                    latest_high.pivot_index if latest_high is not None else None
                ),
                latest_low_pivot_index=(
                    latest_low.pivot_index if latest_low is not None else None
                ),
                available_at=swing.available_at,
                retrieved_at=swing.retrieved_at,
                usable_at=swing.usable_at,
                snapshot_id=swing.snapshot_id,
            )
        )
    return tuple(events)


def latest_trend(events: tuple[TrendEvent, ...]) -> TrendEvent | None:
    """Latest observed state in this ledger, not a predictive trade signal."""
    return events[-1] if events else None
