"""Retrospective, horizon-purged holdout labels for causal setup events.

A held-out historical period is not a prospectively collected validation set.
No labels or outcomes are incorporated into upstream event generation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from technical_engine.data import OHLCVDataset, require_valid_dataset
from technical_engine.setups import SetupConfig, SetupEvent, setup_events

Partition = Literal["DEVELOPMENT", "HOLDOUT"]
LabelStatus = Literal["MATURED", "CENSORED"]


@dataclass(frozen=True)
class ForwardEvaluationConfig:
    cutoff_session: date
    horizons: tuple[int, ...] = (1, 5, 10)
    embargo_bars: int = 0
    setup: SetupConfig = SetupConfig()

    def __post_init__(self) -> None:
        if not isinstance(self.cutoff_session, date) or isinstance(self.cutoff_session, datetime):
            raise ValueError("cutoff_session must be a date")
        if (
            not isinstance(self.horizons, tuple)
            or not self.horizons
            or any(
                not isinstance(horizon, int) or isinstance(horizon, bool) or horizon < 1
                for horizon in self.horizons
            )
            or len(set(self.horizons)) != len(self.horizons)
            or tuple(sorted(self.horizons)) != self.horizons
        ):
            raise ValueError("horizons must be a nonempty sorted unique tuple of positive integers")
        if (
            not isinstance(self.embargo_bars, int)
            or isinstance(self.embargo_bars, bool)
            or self.embargo_bars < 0
        ):
            raise ValueError("embargo_bars must be a nonnegative integer")
        if not isinstance(self.setup, SetupConfig):
            raise TypeError("setup must be a SetupConfig")


@dataclass(frozen=True)
class ForwardReturnLabel:
    event_index: int
    event_kind: str
    event_direction: str
    event_session: date
    observation_index: int
    event_usable_at: datetime
    breakout_id: str
    partition: Partition
    horizon_bars: int
    status: LabelStatus
    label_end_index: int | None
    label_end_session: date | None
    start_close: float
    end_close: float | None
    simple_return: float | None
    directional_return: float | None
    snapshot_id: str


@dataclass(frozen=True)
class ReturnSummary:
    partition: Partition
    event_kind: str
    horizon_bars: int
    matured_count: int
    censored_count: int
    mean_simple_return: float | None
    mean_directional_return: float | None
    directional_positive_fraction: float | None


@dataclass(frozen=True)
class ForwardEvaluation:
    labels: tuple[ForwardReturnLabel, ...]
    summaries: tuple[ReturnSummary, ...]
    snapshot_id: str
    cutoff_session: date
    method: str = "retrospective_chronological_holdout_not_prospective"


def _mean(values: list[float]) -> float | None:
    return math.fsum(values) / len(values) if values else None


def evaluate_forward_returns(
    dataset: OHLCVDataset,
    config: ForwardEvaluationConfig,
    *,
    events: tuple[SetupEvent, ...] | None = None,
) -> ForwardEvaluation:
    """Label close-to-close returns without using outcomes to construct setups.

    Development labels whose outcome end is after the cutoff are CENSORED;
    holdout labels start only beyond the configured post-cutoff embargo.
    Unobserved horizon endpoints are censored, never assigned zero returns.
    Observation positions represent dataset bars, not calendar days.
    """
    require_valid_dataset(dataset)
    if not isinstance(config, ForwardEvaluationConfig):
        raise TypeError("config must be a ForwardEvaluationConfig")
    bars = dataset.bars
    if not bars[0].session <= config.cutoff_session < bars[-1].session:
        raise ValueError("cutoff_session must lie inside history, before its last bar")
    cutoff_index = max(
        index for index, bar in enumerate(bars) if bar.session <= config.cutoff_session
    )
    if events is None:
        events = setup_events(dataset, config.setup)
    if not isinstance(events, tuple):
        raise TypeError("events must be a tuple")
    # Do not silently evaluate foreign or fabricated event records.
    reference = setup_events(dataset, config.setup)
    if events != reference:
        raise ValueError("events must exactly match this dataset and setup configuration")

    labels: list[ForwardReturnLabel] = []
    for event in events:
        index = event.observation_index
        if index <= cutoff_index:
            partition: Partition = "DEVELOPMENT"
        elif index > cutoff_index + config.embargo_bars:
            partition = "HOLDOUT"
        else:
            continue
        for horizon in config.horizons:
            end_index = index + horizon
            matured = end_index < len(bars)
            if partition == "DEVELOPMENT":
                matured = matured and end_index <= cutoff_index
            end_bar = bars[end_index] if matured else None
            simple_return = end_bar.close / bars[index].close - 1 if end_bar is not None else None
            directional_return = (
                (simple_return if event.direction == "UP" else -simple_return)
                if simple_return is not None
                else None
            )
            labels.append(
                ForwardReturnLabel(
                    event_index=event.event_index,
                    event_kind=event.kind,
                    event_direction=event.direction,
                    event_session=event.observation_session,
                    observation_index=index,
                    event_usable_at=event.usable_at,
                    breakout_id=event.breakout_id,
                    partition=partition,
                    horizon_bars=horizon,
                    status="MATURED" if matured else "CENSORED",
                    label_end_index=end_index if matured else None,
                    label_end_session=end_bar.session if end_bar is not None else None,
                    start_close=bars[index].close,
                    end_close=end_bar.close if end_bar is not None else None,
                    simple_return=simple_return,
                    directional_return=directional_return,
                    snapshot_id=dataset.snapshot_id,
                )
            )

    summaries: list[ReturnSummary] = []
    for partition in ("DEVELOPMENT", "HOLDOUT"):
        for kind in ("BREAKOUT", "RETEST", "FAILED_BREAKOUT"):
            for horizon in config.horizons:
                chosen = [
                    label
                    for label in labels
                    if label.partition == partition
                    and label.event_kind == kind
                    and label.horizon_bars == horizon
                ]
                matured_labels = [label for label in chosen if label.status == "MATURED"]
                simple = [
                    label.simple_return
                    for label in matured_labels
                    if label.simple_return is not None
                ]
                directional = [
                    label.directional_return
                    for label in matured_labels
                    if label.directional_return is not None
                ]
                summaries.append(
                    ReturnSummary(
                        partition=partition,
                        event_kind=kind,
                        horizon_bars=horizon,
                        matured_count=len(matured_labels),
                        censored_count=len(chosen) - len(matured_labels),
                        mean_simple_return=_mean(simple),
                        mean_directional_return=_mean(directional),
                        directional_positive_fraction=(
                            sum(value > 0 for value in directional) / len(directional)
                            if directional
                            else None
                        ),
                    )
                )
    return ForwardEvaluation(
        labels=tuple(labels),
        summaries=tuple(summaries),
        snapshot_id=dataset.snapshot_id,
        cutoff_session=config.cutoff_session,
    )
