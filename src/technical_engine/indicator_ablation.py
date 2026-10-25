"""TAE-005B: prespecified descriptive indicator-context ablations.

Four fixed same-bar contexts, shared feature-eligible cohort, and a common
TAE-003 horizon-purged baseline. No inferred predictive edge or trading fills.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Literal

from technical_engine.artifacts import canonical_json, sha256
from technical_engine.data import OHLCVDataset
from technical_engine.forward_evaluation import ForwardReturnLabel, evaluate_forward_returns
from technical_engine.indicators import IndicatorConfig, compute_features
from technical_engine.statistical_protocol import StatisticalProtocolPlan

Context = Literal["RSI", "EMA", "MOMENTUM", "ATR"]
_CONTEXTS: tuple[Context, ...] = ("RSI", "EMA", "MOMENTUM", "ATR")


@dataclass(frozen=True)
class AblationPlan:
    """Prespecified context rules; only the default indicator parameters apply."""

    statistical: StatisticalProtocolPlan
    indicator: IndicatorConfig = IndicatorConfig()

    def __post_init__(self) -> None:
        if not isinstance(self.statistical, StatisticalProtocolPlan):
            raise TypeError("statistical must be StatisticalProtocolPlan")
        if not isinstance(self.indicator, IndicatorConfig):
            raise TypeError("indicator must be IndicatorConfig")
        if self.indicator != IndicatorConfig():
            raise ValueError("TAE-005B fixes all indicator parameters to project defaults")
        if any(item.event_kind != "BREAKOUT" for item in self.statistical.hypotheses):
            raise ValueError("TAE-005B is prespecified for BREAKOUT events only")

    def fingerprint(self) -> str:
        return sha256(
            canonical_json(
                {
                    "contract": "tae-005b-v1",
                    "statistical_plan_sha256": self.statistical.fingerprint(),
                    "indicator": self.indicator.to_dict(),
                    "contexts": list(_CONTEXTS),
                }
            )
        )


@dataclass(frozen=True)
class AblationRow:
    hypothesis_id: str
    partition: str
    horizon_bars: int
    treatment: str
    eligible_count: int
    matured_count: int
    censored_count: int
    mean_directional_return: float | None
    positive_fraction: float | None
    # Difference against the same maturity-matched unfiltered eligible cohort.
    baseline_mean_directional_return: float | None
    descriptive_difference: float | None
    inference_status: str = "NOT_ESTABLISHED"


@dataclass(frozen=True)
class AblationAudit:
    study_id: str
    plan_sha256: str
    snapshot_sha256: str
    rows: tuple[AblationRow, ...]
    method: str = "retrospective_same_cohort_descriptive_ablation"
    research_acceptance: str = "NOT_ESTABLISHED"


def _context_states(
    row: dict[str, object], close: float, direction: str
) -> dict[Context, bool] | None:
    """Require complete, event-time feature availability for every context."""
    keys = ("rsi_14", "ema_9", "ema_21", "roc_10", "macd_histogram_12_26_9", "atr_14")
    values = [row[key] for key in keys]
    if any(value is None for value in values):
        return None
    if any(not isinstance(value, (float, int)) or not math.isfinite(value) for value in values):
        raise ValueError("indicator context contains invalid numeric value")
    rsi, ema_fast, ema_slow, roc, histogram, atr = values
    up = direction == "UP"
    if not up and direction != "DOWN":
        raise ValueError("unknown setup direction")
    return {
        "RSI": rsi >= 50 if up else rsi < 50,
        "EMA": close > ema_fast > ema_slow if up else close < ema_fast < ema_slow,
        "MOMENTUM": roc > 0 and histogram > 0 if up else roc < 0 and histogram < 0,
        # High ATR/close is a context, not direction-specific alpha.
        "ATR": atr / close >= 0.02,
    }


def _mean(labels: list[ForwardReturnLabel]) -> float | None:
    returns = [label.directional_return for label in labels]
    if any(value is None or not math.isfinite(value) for value in returns):
        raise ValueError("matured label has missing/invalid directional return")
    return math.fsum(returns) / len(returns) if returns else None


def audit_indicator_ablations(dataset: OHLCVDataset, plan: AblationPlan) -> AblationAudit:
    """Compare fixed contexts without choosing thresholds using outcome labels.

    All treatment groups share the same feature-complete cohort; baseline and
    treatment summaries use matured labels only. Complements and differences
    are descriptive and do NOT correct for dependence or multiple comparisons.
    """
    if not isinstance(plan, AblationPlan):
        raise TypeError("plan must be AblationPlan")
    evaluation = evaluate_forward_returns(dataset, plan.statistical.forward)
    features = compute_features(dataset, plan.indicator)
    flags: dict[int, dict[Context, bool] | None] = {}
    for label in evaluation.labels:
        index = label.observation_index
        if index not in flags:
            flags[index] = _context_states(
                features[index], dataset.bars[index].close, label.event_direction
            )

    rows: list[AblationRow] = []
    for hypothesis in plan.statistical.hypotheses:
        for partition in ("DEVELOPMENT", "HOLDOUT"):
            selected = [
                label
                for label in evaluation.labels
                if label.partition == partition
                and label.event_kind == hypothesis.event_kind
                and label.horizon_bars == hypothesis.horizon_bars
                and flags[label.observation_index] is not None
            ]
            baseline = [label for label in selected if label.status == "MATURED"]
            baseline_mean = _mean(baseline)
            for omitted in (None, *_CONTEXTS):
                if omitted is None:
                    name = "ALL_CONTEXTS"
                    enabled = _CONTEXTS
                else:
                    name = f"WITHOUT_{omitted}"
                    enabled = tuple(key for key in _CONTEXTS if key != omitted)
                chosen = [
                    label
                    for label in selected
                    if all(flags[label.observation_index][key] for key in enabled)
                ]
                matured = [label for label in chosen if label.status == "MATURED"]
                observed_mean = _mean(matured)
                rows.append(
                    AblationRow(
                        hypothesis_id=hypothesis.hypothesis_id,
                        partition=partition,
                        horizon_bars=hypothesis.horizon_bars,
                        treatment=name,
                        eligible_count=len(chosen),
                        matured_count=len(matured),
                        censored_count=len(chosen) - len(matured),
                        mean_directional_return=observed_mean,
                        positive_fraction=(
                            sum(label.directional_return > 0 for label in matured) / len(matured)
                            if matured
                            else None
                        ),
                        baseline_mean_directional_return=baseline_mean,
                        descriptive_difference=(
                            observed_mean - baseline_mean
                            if observed_mean is not None and baseline_mean is not None
                            else None
                        ),
                    )
                )
            rows.append(
                AblationRow(
                    hypothesis_id=hypothesis.hypothesis_id,
                    partition=partition,
                    horizon_bars=hypothesis.horizon_bars,
                    treatment="UNFILTERED_ELIGIBLE",
                    eligible_count=len(selected),
                    matured_count=len(baseline),
                    censored_count=len(selected) - len(baseline),
                    mean_directional_return=baseline_mean,
                    positive_fraction=(
                        sum(label.directional_return > 0 for label in baseline) / len(baseline)
                        if baseline
                        else None
                    ),
                    baseline_mean_directional_return=baseline_mean,
                    descriptive_difference=0.0 if baseline_mean is not None else None,
                )
            )
    return AblationAudit(
        study_id=plan.statistical.study_id,
        plan_sha256=plan.fingerprint(),
        snapshot_sha256=sha256(canonical_json(dataset.to_dict())),
        rows=tuple(rows),
    )
