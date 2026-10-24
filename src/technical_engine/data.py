"""Provider-neutral, point-in-time daily OHLCV input contracts.

One dataset is one symbol, provider, adjustment policy, and captured snapshot.
Sessions must be explicitly ordered; this module never repairs, sorts, or fills
data. An exchange calendar is deliberately not inferred from calendar dates.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, fields
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

SCHEMA_VERSION = "1.0.0"


def _timestamp(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be an ISO 8601 timestamp")
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO 8601 timestamp") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")
    return result


@dataclass(frozen=True)
class CorporateAction:
    """Optional provider-supplied action metadata; no adjustment is computed.

    ``available_at`` identifies the knowledge time of this metadata when known.
    A missing factor or amount is unknown, never an implicit neutral adjustment.
    """

    action_type: str
    ex_date: date
    adjustment_factor: float | None = None
    amount: float | None = None
    currency: str | None = None
    available_at: datetime | None = None
    status: str = "reported"
    details: str = ""

    def to_dict(self) -> dict[str, Any]:
        result = {field.name: getattr(self, field.name) for field in fields(self)}
        result["ex_date"] = self.ex_date.isoformat()
        result["available_at"] = self.available_at.isoformat() if self.available_at else None
        return result

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> CorporateAction:
        if not isinstance(value, Mapping) or set(value) != {field.name for field in fields(cls)}:
            raise ValueError("Corporate action fields do not match schema")
        result = dict(value)
        if not isinstance(result["ex_date"], str):
            raise ValueError("ex_date must be an ISO 8601 date")
        try:
            result["ex_date"] = date.fromisoformat(result["ex_date"])
        except ValueError as exc:
            raise ValueError("ex_date must be an ISO 8601 date") from exc
        if result["available_at"] is not None:
            result["available_at"] = _timestamp(result["available_at"], "action available_at")
        return cls(**result)


@dataclass(frozen=True)
class OHLCVBar:
    """Daily bar with provenance and explicit earliest usable knowledge time.

    ``available_at`` is when this exact adjusted/revised value became available,
    not simply its exchange session. ``retrieved_at`` records snapshot capture.
    ``corporate_actions`` carries caller-supplied structured event metadata;
    normalization never infers actions or applies price adjustments.
    """

    symbol: str
    session: date
    open: float
    high: float
    low: float
    close: float
    volume: float
    provider: str
    retrieved_at: datetime
    available_at: datetime
    adjustment_policy: str
    snapshot_id: str
    corporate_actions: tuple[CorporateAction, ...] = ()
    quality_status: str = "valid"

    def to_dict(self) -> dict[str, Any]:
        result = {field.name: getattr(self, field.name) for field in fields(self)}
        result["session"] = self.session.isoformat()
        result["retrieved_at"] = self.retrieved_at.isoformat()
        result["available_at"] = self.available_at.isoformat()
        result["corporate_actions"] = [action.to_dict() for action in self.corporate_actions]
        return result

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> OHLCVBar:
        expected = {field.name for field in fields(cls)}
        if not isinstance(value, Mapping) or set(value) != expected:
            raise ValueError("OHLCV bar fields do not match schema")
        result = dict(value)
        session = result["session"]
        if not isinstance(session, str):
            raise ValueError("session must be an ISO 8601 date")
        try:
            result["session"] = date.fromisoformat(session)
        except ValueError as exc:
            raise ValueError("session must be an ISO 8601 date") from exc
        result["retrieved_at"] = _timestamp(result["retrieved_at"], "retrieved_at")
        result["available_at"] = _timestamp(result["available_at"], "available_at")
        actions = result["corporate_actions"]
        if not isinstance(actions, list):
            raise ValueError("corporate_actions must be an array")
        result["corporate_actions"] = tuple(CorporateAction.from_dict(action) for action in actions)
        return cls(**result)


@dataclass(frozen=True)
class OHLCVDataset:
    bars: tuple[OHLCVBar, ...]
    snapshot_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "snapshot_id": self.snapshot_id,
            "bars": [bar.to_dict() for bar in self.bars],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> OHLCVDataset:
        if not isinstance(value, Mapping) or set(value) != {
            "schema_version",
            "snapshot_id",
            "bars",
        }:
            raise ValueError("OHLCV dataset fields do not match schema")
        if value["schema_version"] != SCHEMA_VERSION:
            raise ValueError("Unsupported OHLCV schema_version")
        if not isinstance(value["bars"], list):
            raise ValueError("bars must be an array")
        if not all(isinstance(bar, Mapping) for bar in value["bars"]):
            raise ValueError("Each bar must be an object")
        result = cls(
            bars=tuple(OHLCVBar.from_dict(bar) for bar in value["bars"]),
            snapshot_id=value["snapshot_id"],
        )
        require_valid_dataset(result)
        return result


@dataclass(frozen=True)
class DataQualityReport:
    snapshot_id: str
    row_count: int
    minimum_history: int
    errors: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def is_valid(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "snapshot_id": self.snapshot_id,
            "row_count": self.row_count,
            "minimum_history": self.minimum_history,
            "is_valid": self.is_valid,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


def _nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _aware_timestamp(value: object) -> bool:
    return (
        isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None
    )


def _number(value: object) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def validate_dataset(
    dataset: OHLCVDataset,
    min_history: int = 1,
    *,
    expected_sessions: Iterable[date] | None = None,
) -> DataQualityReport:
    """Return quality findings without modifying input.

    Supply exchange-calendar sessions to detect absent observations, including
    missing start/end sessions. Without that calendar, only observed rows can
    be validated; weekends and exchange holidays are not fabricated as gaps.
    Zero volume is allowed and flagged. Suspect data is flagged, invalid data
    rejected. Partial indicator warm-up is a separate analytical concern.

    Availability receives a broad causal sanity bound: it cannot precede the
    earliest possible session start across exchange timezones (midnight at
    UTC+14). This instant-based bound is invariant to timestamp representation.
    It does not establish the actual exchange close or historical knowledge;
    callers must supply and substantiate those provider-specific facts.
    """
    if not isinstance(min_history, int) or isinstance(min_history, bool) or min_history < 1:
        raise ValueError("min_history must be a positive integer")
    errors: list[str] = []
    warnings: list[str] = []
    if not _nonempty_string(dataset.snapshot_id):
        errors.append("snapshot_id must be a nonempty string")
    if not isinstance(dataset.bars, tuple):
        errors.append("bars must be an immutable tuple")
    if len(dataset.bars) < min_history:
        errors.append(f"Insufficient history: {len(dataset.bars)} rows; require {min_history}")
    sessions: list[date] = []
    symbols: set[str] = set()
    providers: set[str] = set()
    policies: set[str] = set()
    for index, bar in enumerate(dataset.bars):
        prefix = f"row {index}: "
        if not isinstance(bar, OHLCVBar):
            errors.append(prefix + "must be an OHLCVBar")
            continue
        for name in ("symbol", "provider", "adjustment_policy", "snapshot_id"):
            if not _nonempty_string(getattr(bar, name)):
                errors.append(prefix + f"{name} must be a nonempty string")
        if _nonempty_string(bar.symbol):
            symbols.add(bar.symbol)
        if _nonempty_string(bar.provider):
            providers.add(bar.provider)
        if _nonempty_string(bar.adjustment_policy):
            policies.add(bar.adjustment_policy)
        if bar.snapshot_id != dataset.snapshot_id:
            errors.append(prefix + "snapshot_id differs from dataset snapshot_id")
        if not isinstance(bar.session, date) or isinstance(bar.session, datetime):
            errors.append(prefix + "session must be a date")
        else:
            sessions.append(bar.session)
        for name in ("open", "high", "low", "close"):
            value = getattr(bar, name)
            if not _number(value) or value <= 0:
                errors.append(prefix + f"{name} must be finite and positive")
        if all(_number(getattr(bar, name)) for name in ("open", "high", "low", "close")):
            if not bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high:
                errors.append(prefix + "invalid OHLC relationships")
        if not _number(bar.volume) or bar.volume < 0:
            errors.append(prefix + "volume must be finite and nonnegative")
        elif bar.volume == 0:
            warnings.append(prefix + "zero volume")
        for name in ("retrieved_at", "available_at"):
            if not _aware_timestamp(getattr(bar, name)):
                errors.append(prefix + f"{name} must be a timezone-aware timestamp")
        if _aware_timestamp(bar.retrieved_at) and _aware_timestamp(bar.available_at):
            if bar.available_at > bar.retrieved_at:
                errors.append(prefix + "available_at is later than retrieved_at")
        if (
            isinstance(bar.session, date)
            and not isinstance(bar.session, datetime)
            and _aware_timestamp(bar.available_at)
            and bar.available_at
            < datetime.combine(bar.session, time.min, tzinfo=timezone(timedelta(hours=14)))
        ):
            errors.append(prefix + "available_at precedes the earliest possible session start")
        if not isinstance(bar.corporate_actions, tuple):
            errors.append(prefix + "corporate_actions must be an immutable tuple")
        else:
            for action_index, action in enumerate(bar.corporate_actions):
                action_prefix = prefix + f"corporate action {action_index}: "
                if not isinstance(action, CorporateAction):
                    errors.append(action_prefix + "must be a CorporateAction")
                    continue
                if not _nonempty_string(action.action_type) or not _nonempty_string(action.status):
                    errors.append(action_prefix + "action_type and status must be nonempty strings")
                if not isinstance(action.ex_date, date) or isinstance(action.ex_date, datetime):
                    errors.append(action_prefix + "ex_date must be a date")
                for name in ("adjustment_factor", "amount"):
                    value = getattr(action, name)
                    if value is not None and (
                        not _number(value)
                        or (value <= 0 if name == "adjustment_factor" else value < 0)
                    ):
                        errors.append(action_prefix + f"{name} must be finite and valid")
                if action.currency is not None and not _nonempty_string(action.currency):
                    errors.append(
                        action_prefix + "currency must be a nonempty string when supplied"
                    )
                if not isinstance(action.details, str):
                    errors.append(action_prefix + "details must be a string")
                if action.available_at is None:
                    warnings.append(action_prefix + "metadata availability is unknown")
                elif not _aware_timestamp(action.available_at):
                    errors.append(action_prefix + "available_at must be a timezone-aware timestamp")
                elif _aware_timestamp(bar.available_at) and action.available_at > bar.available_at:
                    errors.append(action_prefix + "metadata available after the row available_at")
        if bar.quality_status not in ("valid", "suspect", "invalid"):
            errors.append(prefix + "unsupported quality_status")
        elif bar.quality_status == "invalid":
            errors.append(prefix + "data marked invalid")
        elif bar.quality_status == "suspect":
            warnings.append(prefix + "data marked suspect")
    if len(symbols) > 1:
        errors.append("Dataset contains multiple symbols")
    if len(providers) > 1:
        errors.append("Dataset contains multiple providers")
    if len(policies) > 1:
        errors.append("Dataset contains multiple adjustment policies")
    if len(set(sessions)) != len(sessions):
        errors.append("Duplicate trading sessions")
    if any(left >= right for left, right in zip(sessions, sessions[1:], strict=False)):
        errors.append("Trading sessions must be strictly increasing")
    if expected_sessions is None:
        warnings.append("Calendar completeness not assessed: expected_sessions not supplied")
    else:
        expected = tuple(expected_sessions)
        if any(not isinstance(item, date) or isinstance(item, datetime) for item in expected):
            raise ValueError("expected_sessions must contain dates")
        missing = sorted(set(expected) - set(sessions))
        unexpected = sorted(set(sessions) - set(expected))
        if missing:
            errors.append(
                "Missing expected sessions: " + ", ".join(item.isoformat() for item in missing)
            )
        if unexpected:
            errors.append(
                "Unexpected sessions: " + ", ".join(item.isoformat() for item in unexpected)
            )
    return DataQualityReport(
        snapshot_id=dataset.snapshot_id,
        row_count=len(dataset.bars),
        minimum_history=min_history,
        errors=tuple(errors),
        warnings=tuple(warnings),
    )


def require_valid_dataset(
    dataset: OHLCVDataset,
    min_history: int = 1,
    *,
    expected_sessions: Iterable[date] | None = None,
) -> DataQualityReport:
    report = validate_dataset(dataset, min_history, expected_sessions=expected_sessions)
    if not report.is_valid:
        raise ValueError("Invalid OHLCV dataset: " + "; ".join(report.errors))
    return report
