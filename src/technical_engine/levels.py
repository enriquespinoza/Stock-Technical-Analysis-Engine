"""Causal descriptive support and resistance levels from confirmed swing points.

Levels are event-sourced. Later swing confirmations produce new immutable
snapshots rather than rewriting any previously observed level state. These are
historical price clusters, not tradable signals or claims of active levels.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal

from technical_engine.data import OHLCVDataset
from technical_engine.structure import SwingConfig, confirmed_swings

LevelKind = Literal["SUPPORT", "RESISTANCE"]


@dataclass(frozen=True)
class LevelConfig:
    swing: SwingConfig = field(default_factory=SwingConfig)
    merge_tolerance_bps: float = 50.0

    def __post_init__(self) -> None:
        if not isinstance(self.swing, SwingConfig):
            raise TypeError("swing must be a SwingConfig")
        tolerance = self.merge_tolerance_bps
        if (
            isinstance(tolerance, bool)
            or not isinstance(tolerance, (int, float))
            or not math.isfinite(tolerance)
            or tolerance < 0
        ):
            raise ValueError("merge_tolerance_bps must be finite and nonnegative")


@dataclass(frozen=True)
class LevelEvent:
    """Immutable state of one level *after* a confirmed contributing swing."""

    level_id: str
    kind: LevelKind
    event_index: int
    pivot_index: int
    confirmation_index: int
    pivot_session: date
    confirmation_session: date
    pivot_price: float
    anchor_price: float
    mean_price: float
    minimum_price: float
    maximum_price: float
    swing_count: int
    first_confirmation_index: int
    first_confirmation_session: date
    available_at: datetime
    retrieved_at: datetime
    usable_at: datetime
    snapshot_id: str


def level_events(
    dataset: OHLCVDataset, config: LevelConfig | None = None
) -> tuple[LevelEvent, ...]:
    """Build an append-only ledger of level confirmations.

    A level is born when its first swing is confirmed. Subsequent confirmed
    swings of the same kind join the nearest *original anchor* within the
    tolerance. The anchor never moves, avoiding order-dependent cluster drift.
    Ties choose the earliest level. Each update produces a new event, never
    changes an earlier one. Levels are scoped to an input snapshot.
    """
    config = LevelConfig() if config is None else config
    if not isinstance(config, LevelConfig):
        raise TypeError("config must be a LevelConfig")

    events: list[LevelEvent] = []
    latest: dict[str, LevelEvent] = {}
    ids_by_kind: dict[LevelKind, list[str]] = {"SUPPORT": [], "RESISTANCE": []}

    for swing in confirmed_swings(dataset, config.swing):
        kind: LevelKind = "RESISTANCE" if swing.kind == "HIGH" else "SUPPORT"
        matching_id: str | None = None
        smallest_bps = math.inf
        for level_id in ids_by_kind[kind]:
            existing = latest[level_id]
            distance_bps = abs(swing.price - existing.anchor_price) / existing.anchor_price
            distance_bps *= 10_000.0
            if distance_bps <= config.merge_tolerance_bps and distance_bps < smallest_bps:
                matching_id = level_id
                smallest_bps = distance_bps

        previous = latest[matching_id] if matching_id is not None else None
        if previous is None:
            prefix = "R" if kind == "RESISTANCE" else "S"
            matching_id = f"{prefix}-{len(ids_by_kind[kind]) + 1:06d}"
            ids_by_kind[kind].append(matching_id)
            count = 1
            anchor = swing.price
            mean = swing.price
            minimum = swing.price
            maximum = swing.price
            first_index = swing.confirmation_index
            first_session = swing.confirmation_session
            available_at = swing.available_at
            retrieved_at = swing.retrieved_at
        else:
            count = previous.swing_count + 1
            anchor = previous.anchor_price
            mean = previous.mean_price + (swing.price - previous.mean_price) / count
            minimum = min(previous.minimum_price, swing.price)
            maximum = max(previous.maximum_price, swing.price)
            first_index = previous.first_confirmation_index
            first_session = previous.first_confirmation_session
            available_at = max(previous.available_at, swing.available_at)
            retrieved_at = max(previous.retrieved_at, swing.retrieved_at)

        event = LevelEvent(
            level_id=matching_id,
            kind=kind,
            event_index=len(events),
            pivot_index=swing.pivot_index,
            confirmation_index=swing.confirmation_index,
            pivot_session=swing.pivot_session,
            confirmation_session=swing.confirmation_session,
            pivot_price=swing.price,
            anchor_price=anchor,
            mean_price=mean,
            minimum_price=minimum,
            maximum_price=maximum,
            swing_count=count,
            first_confirmation_index=first_index,
            first_confirmation_session=first_session,
            available_at=available_at,
            retrieved_at=retrieved_at,
            usable_at=max(available_at, retrieved_at),
            snapshot_id=swing.snapshot_id,
        )
        latest[matching_id] = event
        events.append(event)

    return tuple(events)


def latest_levels(events: tuple[LevelEvent, ...]) -> tuple[LevelEvent, ...]:
    """Return latest snapshots, ordered by the levels' first appearances.

    This is *not* a claim that the levels remain active or unbroken. Call only
    with a ledger constructed from the appropriate as-of dataset prefix.
    """
    by_id: dict[str, LevelEvent] = {}
    for event in events:
        by_id[event.level_id] = event
    return tuple(by_id.values())
