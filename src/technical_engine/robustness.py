"""Exploratory robustness diagnostics for retrospective TAE-003 return labels.

This module cannot certify independent validation, hypothesis preregistration,
historical point-in-time availability, or deployable economic performance.
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass
from typing import Literal

from technical_engine.data import OHLCVDataset, require_valid_dataset
from technical_engine.forward_evaluation import (
    ForwardEvaluation,
    ForwardEvaluationConfig,
    ForwardReturnLabel,
    evaluate_forward_returns,
)

FindingStatus = Literal[
    "SUPPRESSED_INSUFFICIENT_CLUSTERS",
    "SUPPRESSED_CLUSTER_DOMINANCE",
    "EXPLORATORY_ASSUMPTIONS_UNVERIFIED",
]


@dataclass(frozen=True)
class RobustnessConfig:
    forward: ForwardEvaluationConfig
    analysis_label: str
    seed: int = 2026
    resamples: int = 999
    min_clusters: int = 5
    largest_cluster_limit: float = 0.5
    interval_level: float = 0.95

    def __post_init__(self) -> None:
        if not isinstance(self.forward, ForwardEvaluationConfig):
            raise TypeError("forward must be a ForwardEvaluationConfig")
        if not isinstance(self.analysis_label, str) or not self.analysis_label.strip():
            raise ValueError("analysis_label must be nonempty")
        if not isinstance(self.seed, int) or isinstance(self.seed, bool):
            raise ValueError("seed must be an integer")
        for name, minimum in (("resamples", 99), ("min_clusters", 2)):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
                raise ValueError(f"{name} must be an integer >= {minimum}")
        if (
            isinstance(self.largest_cluster_limit, bool)
            or not isinstance(self.largest_cluster_limit, (float, int))
            or not math.isfinite(self.largest_cluster_limit)
            or not 0 < self.largest_cluster_limit <= 1
        ):
            raise ValueError("largest_cluster_limit must be in (0, 1]")
        if (
            isinstance(self.interval_level, bool)
            or not isinstance(self.interval_level, (float, int))
            or not math.isfinite(self.interval_level)
            or not 0 < self.interval_level < 1
        ):
            raise ValueError("interval_level must be in (0, 1)")


@dataclass(frozen=True)
class RobustnessFinding:
    event_kind: str
    horizon_bars: int
    matured_count: int
    censored_count: int
    overlap_cluster_count: int
    largest_cluster_fraction: float | None
    backfilled_event_count: int
    mean_asset_directional_return: float | None
    mean_benchmark_directional_return: float | None
    mean_excess_directional_return: float | None
    bootstrap_lower: float | None
    bootstrap_upper: float | None
    sign_flip_p: float | None
    holm_adjusted_p: float | None
    status: FindingStatus


@dataclass(frozen=True)
class RobustnessReport:
    analysis_label: str
    asset_snapshot_id: str
    benchmark_snapshot_id: str
    asset_symbol: str
    benchmark_symbol: str
    findings: tuple[RobustnessFinding, ...]
    method: str = "retrospective_holdout_exploratory_not_independently_validated"


def _mean(values: list[float]) -> float | None:
    return math.fsum(values) / len(values) if values else None


def _quantile(ordered: list[float], probability: float) -> float:
    position = (len(ordered) - 1) * probability
    bottom = math.floor(position)
    top = math.ceil(position)
    return ordered[bottom] + (ordered[top] - ordered[bottom]) * (position - bottom)


def _clusters(rows: list[tuple[ForwardReturnLabel, float]]) -> list[list[float]]:
    """Group overlapping exposure windows and repeated breakout identities.

    Connected components are conservative: sharing even one endpoint merges
    otherwise separate observations. No independence is inferred for components.
    """
    parents = list(range(len(rows)))

    def root(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    for index, (left, _) in enumerate(rows):
        for other in range(index):
            right = rows[other][0]
            linked = left.breakout_id == right.breakout_id or (
                left.observation_index <= right.label_end_index
                and right.observation_index <= left.label_end_index
            )
            if linked:
                parents[root(index)] = root(other)
    groups: dict[int, list[float]] = {}
    for index, (_, value) in enumerate(rows):
        groups.setdefault(root(index), []).append(value)
    return list(groups.values())


def _resampling(
    groups: list[list[float]], *, seed: int, replicates: int, confidence: float
) -> tuple[float, float, float]:
    """Cluster bootstrap and sign-flip screen, conditional on strong assumptions.

    Cluster sign-flips require independent, sign-symmetric cluster effects.
    Those assumptions are not testable from one selected historical backfill.
    """
    rng = random.Random(seed)
    flattened = [value for group in groups for value in group]
    observed = math.fsum(flattened) / len(flattened)
    sums = [math.fsum(group) for group in groups]
    lengths = [len(group) for group in groups]
    count = len(groups)
    boot: list[float] = []
    exceed = 0
    for _ in range(replicates):
        selected = [rng.randrange(count) for _ in range(count)]
        numerator = math.fsum(sums[position] for position in selected)
        denominator = sum(lengths[position] for position in selected)
        boot.append(numerator / denominator)
        randomized = math.fsum(total * (1 if rng.randrange(2) else -1) for total in sums)
        if abs(randomized / len(flattened)) >= abs(observed) - 1e-15:
            exceed += 1
    boot.sort()
    tail = (1 - confidence) / 2
    return _quantile(boot, tail), _quantile(boot, 1 - tail), (exceed + 1) / (replicates + 1)


def _holm(raw: list[float | None]) -> list[float | None]:
    """Holm screen over the COMPLETE pre-specified kind-by-horizon family.

    Suppressed tests remain in the family as p=1; they never inflate evidence.
    """
    sized = len(raw)
    ordered = sorted(range(sized), key=lambda index: 1.0 if raw[index] is None else raw[index])
    adjusted: list[float | None] = [None] * sized
    running = 0.0
    for rank, index in enumerate(ordered):
        probability = raw[index] if raw[index] is not None else 1.0
        running = max(running, min(1.0, (sized - rank) * probability))
        if raw[index] is not None:
            adjusted[index] = running
    return adjusted


def validate_return_robustness(
    asset: OHLCVDataset,
    benchmark: OHLCVDataset,
    config: RobustnessConfig,
    *,
    evaluation: ForwardEvaluation | None = None,
) -> RobustnessReport:
    """Benchmark same-session returns; only HOLDOUT MATURED labels are scored.

    Dataset alignment and an exact TAE-003 evaluation match fail closed.
    Results remain exploratory: neither benchmark selection nor protocols nor
    independence assumptions are externally verified by this software.
    """
    if not isinstance(config, RobustnessConfig):
        raise TypeError("config must be a RobustnessConfig")
    require_valid_dataset(asset)
    require_valid_dataset(benchmark)
    if asset.bars[0].symbol == benchmark.bars[0].symbol:
        raise ValueError("benchmark must use a different symbol")
    if asset.bars[0].adjustment_policy != benchmark.bars[0].adjustment_policy:
        raise ValueError("benchmark and asset adjustment policies must match")
    if tuple(bar.session for bar in asset.bars) != tuple(bar.session for bar in benchmark.bars):
        raise ValueError("benchmark sessions must exactly match asset sessions")

    reference = evaluate_forward_returns(asset, config.forward)
    if evaluation is not None and evaluation != reference:
        raise ValueError("evaluation must match the recomputed TAE-003 evidence")
    evaluation = reference

    findings: list[RobustnessFinding] = []
    pvalues: list[float | None] = []
    for kind in ("BREAKOUT", "RETEST", "FAILED_BREAKOUT"):
        for horizon in config.forward.horizons:
            selected = [
                label
                for label in evaluation.labels
                if label.partition == "HOLDOUT"
                and label.event_kind == kind
                and label.horizon_bars == horizon
            ]
            matured = [label for label in selected if label.status == "MATURED"]
            rows: list[tuple[ForwardReturnLabel, float]] = []
            assets: list[float] = []
            baselines: list[float] = []
            for label in matured:
                assert label.label_end_index is not None
                assert label.directional_return is not None
                start = benchmark.bars[label.observation_index].close
                end = benchmark.bars[label.label_end_index].close
                benchmark_return = end / start - 1
                directional = (
                    benchmark_return if label.event_direction == "UP" else -benchmark_return
                )
                baselines.append(directional)
                assets.append(label.directional_return)
                rows.append((label, label.directional_return - directional))
            clusters = _clusters(rows)
            largest = max(len(group) for group in clusters) / len(rows) if rows else None
            status: FindingStatus = "EXPLORATORY_ASSUMPTIONS_UNVERIFIED"
            lower = upper = probability = None
            if len(clusters) < config.min_clusters:
                status = "SUPPRESSED_INSUFFICIENT_CLUSTERS"
            elif largest is not None and largest > config.largest_cluster_limit:
                status = "SUPPRESSED_CLUSTER_DOMINANCE"
            else:
                seed_source = f"{config.seed}|{config.analysis_label}|{kind}|{horizon}".encode()
                local_seed = int.from_bytes(hashlib.sha256(seed_source).digest()[:8], "big")
                lower, upper, probability = _resampling(
                    clusters,
                    seed=local_seed,
                    replicates=config.resamples,
                    confidence=config.interval_level,
                )
            pvalues.append(probability)
            excess = [row[1] for row in rows]
            findings.append(
                RobustnessFinding(
                    event_kind=kind,
                    horizon_bars=horizon,
                    matured_count=len(rows),
                    censored_count=len(selected) - len(matured),
                    overlap_cluster_count=len(clusters),
                    largest_cluster_fraction=largest,
                    backfilled_event_count=sum(
                        label.event_usable_at.date() > label.event_session for label in matured
                    ),
                    mean_asset_directional_return=_mean(assets),
                    mean_benchmark_directional_return=_mean(baselines),
                    mean_excess_directional_return=_mean(excess),
                    bootstrap_lower=lower,
                    bootstrap_upper=upper,
                    sign_flip_p=probability,
                    holm_adjusted_p=None,
                    status=status,
                )
            )
    adjusted = _holm(pvalues)
    from dataclasses import replace

    return RobustnessReport(
        analysis_label=config.analysis_label,
        asset_snapshot_id=asset.snapshot_id,
        benchmark_snapshot_id=benchmark.snapshot_id,
        asset_symbol=asset.bars[0].symbol,
        benchmark_symbol=benchmark.bars[0].symbol,
        findings=tuple(
            replace(finding, holm_adjusted_p=pvalue)
            for finding, pvalue in zip(findings, adjusted, strict=True)
        ),
    )
