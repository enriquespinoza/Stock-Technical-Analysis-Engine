"""TAE-005A: frozen retrospective evaluation plans and dependence audits.

This module does not calculate significance, confidence intervals, trading
returns, or prospective predictive power. It reuses TAE-003's causal
event-ledger and horizon-purged chronological holdout.
"""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from typing import Literal

from technical_engine.artifacts import canonical_json, sha256
from technical_engine.data import OHLCVDataset
from technical_engine.forward_evaluation import (
    ForwardEvaluationConfig,
    ForwardReturnLabel,
    Partition,
    evaluate_forward_returns,
)
from technical_engine.setups import SetupKind

Outcome = Literal["DIRECTIONAL_CLOSE_RETURN"]
_KINDS = frozenset(("BREAKOUT", "RETEST", "FAILED_BREAKOUT"))
_ID = re.compile(r"[A-Z][A-Z0-9_-]{0,63}\Z")


@dataclass(frozen=True)
class StatisticalHypothesis:
    """Predeclared event-kind / horizon slice; no parameter optimization."""

    hypothesis_id: str
    event_kind: SetupKind
    horizon_bars: int
    outcome: Outcome = "DIRECTIONAL_CLOSE_RETURN"

    def __post_init__(self) -> None:
        if not isinstance(self.hypothesis_id, str) or not _ID.fullmatch(self.hypothesis_id):
            raise ValueError("hypothesis_id must use uppercase letters, digits, '_' or '-'")
        if self.event_kind not in _KINDS:
            raise ValueError("event_kind must be an existing TAE-002D setup kind")
        if (
            not isinstance(self.horizon_bars, int)
            or isinstance(self.horizon_bars, bool)
            or self.horizon_bars < 1
        ):
            raise ValueError("horizon_bars must be a positive integer")
        if self.outcome != "DIRECTIONAL_CLOSE_RETURN":
            raise ValueError("only directional close-to-close return is supported")


@dataclass(frozen=True)
class StatisticalProtocolPlan:
    """Frozen plan; its hash is a fingerprint, NOT evidence of preregistration."""

    study_id: str
    forward: ForwardEvaluationConfig
    hypotheses: tuple[StatisticalHypothesis, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.study_id, str) or not _ID.fullmatch(self.study_id):
            raise ValueError("study_id must use uppercase letters, digits, '_' or '-'")
        if not isinstance(self.forward, ForwardEvaluationConfig):
            raise TypeError("forward must be a ForwardEvaluationConfig")
        if not isinstance(self.hypotheses, tuple) or not self.hypotheses:
            raise ValueError("hypotheses must be a nonempty tuple")
        if any(not isinstance(item, StatisticalHypothesis) for item in self.hypotheses):
            raise TypeError("hypotheses must contain StatisticalHypothesis records")
        ids = [item.hypothesis_id for item in self.hypotheses]
        slices = [(item.event_kind, item.horizon_bars) for item in self.hypotheses]
        if len(set(ids)) != len(ids) or len(set(slices)) != len(slices):
            raise ValueError("duplicate hypothesis id or event-kind/horizon slice")
        if any(item.horizon_bars not in self.forward.horizons for item in self.hypotheses):
            raise ValueError("every hypothesis horizon must be in forward.horizons")

    def fingerprint(self) -> str:
        payload = asdict(self)
        payload["forward"]["cutoff_session"] = self.forward.cutoff_session.isoformat()
        return sha256(canonical_json({"contract": "tae-005a-v1", "plan": payload}))


@dataclass(frozen=True)
class StatisticalAuditRow:
    hypothesis_id: str
    partition: Partition
    event_kind: SetupKind
    horizon_bars: int
    matured_count: int
    censored_count: int
    mean_directional_return: float | None
    directional_positive_fraction: float | None
    unique_breakout_ids: int
    overlapping_outcome_pairs: int
    shared_breakout_pairs: int
    dependency_components: int
    inference_status: str = "NOT_ESTABLISHED"


@dataclass(frozen=True)
class StatisticalProtocolAudit:
    study_id: str
    plan_sha256: str
    snapshot_id: str
    snapshot_sha256: str
    rows: tuple[StatisticalAuditRow, ...]
    method: str = "retrospective_descriptive_dependency_audit_not_inference"
    research_acceptance: str = "NOT_ESTABLISHED"


def _dependencies(labels: list[ForwardReturnLabel]) -> tuple[int, int, int]:
    """Count dependent pairs and components, not independent effective sample size.

    Outcome intervals cover the *future* bars (start, end], excluding the
    event close. Connected components include both shared breakout identity
    and any overlapping future interval. Even separate components may be
    correlated due to market conditions or shared source data.
    """
    n = len(labels)
    parent = list(range(n))

    def root(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    overlap_pairs = 0
    shared_pairs = 0
    for i, first in enumerate(labels):
        for j in range(i + 1, n):
            second = labels[j]
            shared = first.breakout_id == second.breakout_id
            overlap = max(first.observation_index, second.observation_index) < min(
                first.label_end_index, second.label_end_index
            )
            if shared:
                shared_pairs += 1
            if overlap:
                overlap_pairs += 1
            if shared or overlap:
                parent[root(j)] = root(i)

    return overlap_pairs, shared_pairs, len({root(i) for i in range(n)})


def audit_statistical_protocol(
    dataset: OHLCVDataset, plan: StatisticalProtocolPlan
) -> StatisticalProtocolAudit:
    """Audit preselected TAE-003 outcome slices without peeking to select them.

    The caller must store/approve the plan fingerprint BEFORE examining
    holdout results; a software hash cannot prove that this actually occurred.
    No control population, executable fills, independence, or inference is
    established by this function.
    """
    if not isinstance(plan, StatisticalProtocolPlan):
        raise TypeError("plan must be StatisticalProtocolPlan")
    evaluation = evaluate_forward_returns(dataset, plan.forward)
    rows: list[StatisticalAuditRow] = []
    for hypothesis in plan.hypotheses:
        for partition in ("DEVELOPMENT", "HOLDOUT"):
            selected = [
                label
                for label in evaluation.labels
                if label.partition == partition
                and label.event_kind == hypothesis.event_kind
                and label.horizon_bars == hypothesis.horizon_bars
            ]
            matured = [label for label in selected if label.status == "MATURED"]
            returns = [label.directional_return for label in matured]
            # TAE-003 requires non-null returns for matured labels.
            if any(value is None or not math.isfinite(value) for value in returns):
                raise ValueError("TAE-003 matured labels have invalid directional returns")
            overlap, shared, components = _dependencies(matured)
            rows.append(
                StatisticalAuditRow(
                    hypothesis_id=hypothesis.hypothesis_id,
                    partition=partition,
                    event_kind=hypothesis.event_kind,
                    horizon_bars=hypothesis.horizon_bars,
                    matured_count=len(matured),
                    censored_count=len(selected) - len(matured),
                    mean_directional_return=math.fsum(returns) / len(returns) if returns else None,
                    directional_positive_fraction=(
                        sum(value > 0 for value in returns) / len(returns) if returns else None
                    ),
                    unique_breakout_ids=len({label.breakout_id for label in matured}),
                    overlapping_outcome_pairs=overlap,
                    shared_breakout_pairs=shared,
                    dependency_components=components,
                )
            )
    return StatisticalProtocolAudit(
        study_id=plan.study_id,
        plan_sha256=plan.fingerprint(),
        snapshot_id=evaluation.snapshot_id,
        snapshot_sha256=sha256(canonical_json(dataset.to_dict())),
        rows=tuple(rows),
    )
