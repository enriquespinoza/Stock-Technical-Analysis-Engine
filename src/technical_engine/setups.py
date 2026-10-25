"""Causal research events for breakouts, retests, and failed breakouts.

Only previously confirmed support/resistance levels are eligible. A breakout
freezes its reference level; later revisions to level clusters cannot change
past setup events. This module does not place trades or forecast returns.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Literal

from technical_engine.data import OHLCVDataset
from technical_engine.levels import LevelConfig, LevelEvent, LevelKind, level_events
from technical_engine.trends import TrendConfig, TrendEvent, TrendState, trend_events

SetupKind = Literal["BREAKOUT", "RETEST", "FAILED_BREAKOUT"]
BreakoutDirection = Literal["UP", "DOWN"]


@dataclass(frozen=True)
class SetupConfig:
    levels: LevelConfig = field(default_factory=LevelConfig)
    breakout_buffer_bps: float = 0.0
    retest_tolerance_bps: float = 25.0
    max_followup_bars: int = 5

    def __post_init__(self) -> None:
        if not isinstance(self.levels, LevelConfig):
            raise TypeError("levels must be a LevelConfig")
        for name in ("breakout_buffer_bps", "retest_tolerance_bps"):
            value = getattr(self, name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 0 <= value < 10_000
            ):
                raise ValueError(f"{name} must be finite and in [0, 10000) bps")
        if (
            not isinstance(self.max_followup_bars, int)
            or isinstance(self.max_followup_bars, bool)
            or self.max_followup_bars < 1
        ):
            raise ValueError("max_followup_bars must be a positive integer")


@dataclass(frozen=True)
class SetupEvent:
    """Immutable close-of-bar observation, never an actionable trade order."""

    event_index: int
    kind: SetupKind
    direction: BreakoutDirection
    breakout_id: str
    level_id: str
    level_kind: LevelKind
    level_anchor_price: float
    level_confirmation_index: int
    level_confirmation_session: date
    breakout_index: int
    breakout_session: date
    observation_index: int
    observation_session: date
    close: float
    trend_context: TrendState
    available_at: datetime
    retrieved_at: datetime
    usable_at: datetime
    snapshot_id: str


@dataclass
class _ActiveBreakout:
    """Internal mutable state, never exported as research evidence."""

    origin: SetupEvent
    retested: bool = False


def _broken(level: LevelEvent, previous: float, current: float, buffer: float) -> bool:
    if level.kind == "RESISTANCE":
        threshold = level.anchor_price * (1 + buffer / 10_000)
        return previous <= threshold < current
    threshold = level.anchor_price * (1 - buffer / 10_000)
    return previous >= threshold > current


def _failed(origin: SetupEvent, close: float) -> bool:
    anchor = origin.level_anchor_price
    return close < anchor if origin.direction == "UP" else close > anchor


def _retested(origin: SetupEvent, high: float, low: float, close: float, bps: float) -> bool:
    anchor = origin.level_anchor_price
    if origin.direction == "UP":
        return low <= anchor * (1 + bps / 10_000) and close >= anchor
    return high >= anchor * (1 - bps / 10_000) and close <= anchor


def setup_events(
    dataset: OHLCVDataset, config: SetupConfig | None = None
) -> tuple[SetupEvent, ...]:
    """Return point-in-time descriptive setup events in observation order.

    A level confirmed at bar k can trigger a breakout no earlier than k+1.
    A breakout requires crossing its buffered original anchor on *close*,
    relative to the previous bar's close. Follow-ups start on the NEXT bar:
    at most one retest and one later failure within max_followup_bars.
    Failed breakouts take precedence over retests on the same observation.
    A level cannot spawn overlapping active breakout sequences.

    ``trend_context`` is the most recently confirmed TAE-002C state from
    before the observation bar; it is descriptive, never a filter.
    """
    config = SetupConfig() if config is None else config
    if not isinstance(config, SetupConfig):
        raise TypeError("config must be a SetupConfig")

    # level_events validates the dataset through confirmed_swings.
    all_levels = level_events(dataset, config.levels)
    all_trends = trend_events(dataset, TrendConfig(swing=config.levels.swing))
    bars = dataset.bars
    latest: dict[str, LevelEvent] = {}
    active: dict[str, _ActiveBreakout] = {}
    events: list[SetupEvent] = []
    level_pos = 0
    trend_pos = 0
    context: TrendEvent | None = None
    available_at = bars[0].available_at
    retrieved_at = bars[0].retrieved_at

    for i in range(1, len(bars)):
        bar = bars[i]
        available_at = max(available_at, bar.available_at)
        retrieved_at = max(retrieved_at, bar.retrieved_at)

        # Strictly prior confirmations, never a level first confirmed on i.
        while level_pos < len(all_levels) and all_levels[level_pos].confirmation_index < i:
            level = all_levels[level_pos]
            latest[level.level_id] = level
            level_pos += 1
        while trend_pos < len(all_trends) and all_trends[trend_pos].confirmation_index < i:
            context = all_trends[trend_pos]
            trend_pos += 1

        trend_state: TrendState = context.state if context is not None else "INDETERMINATE"

        def record(
            kind: SetupKind,
            origin: SetupEvent,
            index: int,
            *,
            i: int = i,
            bar=bar,
            available_at: datetime = available_at,
            retrieved_at: datetime = retrieved_at,
            context: TrendEvent | None = context,
            trend_state: TrendState = trend_state,
        ) -> SetupEvent:
            relevant_level = latest[origin.level_id]
            known_available = max(available_at, origin.available_at, relevant_level.available_at)
            known_retrieved = max(retrieved_at, origin.retrieved_at, relevant_level.retrieved_at)
            if context is not None:
                known_available = max(known_available, context.available_at)
                known_retrieved = max(known_retrieved, context.retrieved_at)
            return SetupEvent(
                event_index=index,
                kind=kind,
                direction=origin.direction,
                breakout_id=origin.breakout_id,
                level_id=origin.level_id,
                level_kind=origin.level_kind,
                level_anchor_price=origin.level_anchor_price,
                level_confirmation_index=origin.level_confirmation_index,
                level_confirmation_session=origin.level_confirmation_session,
                breakout_index=origin.breakout_index,
                breakout_session=origin.breakout_session,
                observation_index=i,
                observation_session=bar.session,
                close=bar.close,
                trend_context=trend_state,
                available_at=known_available,
                retrieved_at=known_retrieved,
                usable_at=max(known_available, known_retrieved),
                snapshot_id=dataset.snapshot_id,
            )

        just_failed: set[str] = set()
        for level_id, pending in tuple(active.items()):
            origin = pending.origin
            elapsed = i - origin.breakout_index
            if elapsed > config.max_followup_bars:
                del active[level_id]
                continue
            if _failed(origin, bar.close):
                events.append(record("FAILED_BREAKOUT", origin, len(events)))
                just_failed.add(level_id)
                del active[level_id]
            elif not pending.retested and _retested(
                origin, bar.high, bar.low, bar.close, config.retest_tolerance_bps
            ):
                events.append(record("RETEST", origin, len(events)))
                pending.retested = True

        for level_id, level in latest.items():
            if level_id in active or level_id in just_failed:
                continue
            if not _broken(
                level, bars[i - 1].close, bar.close, config.breakout_buffer_bps
            ):
                continue
            direction: BreakoutDirection = "UP" if level.kind == "RESISTANCE" else "DOWN"
            new_id = f"B-{sum(event.kind == 'BREAKOUT' for event in events) + 1:06d}"
            # Seed event; record() creates the official immutable observation.
            seed = SetupEvent(
                event_index=-1,
                kind="BREAKOUT",
                direction=direction,
                breakout_id=new_id,
                level_id=level_id,
                level_kind=level.kind,
                level_anchor_price=level.anchor_price,
                level_confirmation_index=level.confirmation_index,
                level_confirmation_session=level.confirmation_session,
                breakout_index=i,
                breakout_session=bar.session,
                observation_index=i,
                observation_session=bar.session,
                close=bar.close,
                trend_context=trend_state,
                available_at=level.available_at,
                retrieved_at=level.retrieved_at,
                usable_at=level.usable_at,
                snapshot_id=dataset.snapshot_id,
            )
            breakout = record("BREAKOUT", seed, len(events))
            events.append(breakout)
            active[level_id] = _ActiveBreakout(origin=breakout)

    return tuple(events)
