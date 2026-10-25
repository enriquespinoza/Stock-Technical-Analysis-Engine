"""Fail-closed comparison of independently captured thinkorswim swing plots.

This protocol compares *observations*; a CSV or assertion of platform origin
is not independent proof that thinkorswim executed the reference study.
"""

from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from technical_engine.artifacts import canonical_json, sha256
from technical_engine.data import OHLCVDataset, require_valid_dataset
from technical_engine.structure import SwingConfig, confirmed_swings

DifferenceKind = Literal["MISSING", "EXTRA", "PRICE_MISMATCH", "SESSION_MISMATCH"]
_COLUMNS = (
    "kind",
    "pivot_index",
    "confirmation_index",
    "pivot_session",
    "confirmation_session",
    "price",
)


@dataclass(frozen=True)
class ThinkScriptCapture:
    """Operator-supplied chart and script fingerprints; never platform-attested."""

    symbol: str
    aggregation: str
    snapshot_sha256: str
    study_sha256: str
    captured_at: datetime
    bar_count: int
    first_session: date
    last_session: date

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise ValueError("symbol must be nonempty")
        if self.aggregation != "DAY":
            raise ValueError("aggregation must be DAY")
        for name in ("snapshot_sha256", "study_sha256"):
            value = getattr(self, name)
            if (
                not isinstance(value, str)
                or len(value) != 64
                or any(character not in "0123456789abcdef" for character in value)
            ):
                raise ValueError(f"{name} must be lowercase SHA-256 hex")
        if (
            not isinstance(self.captured_at, datetime)
            or self.captured_at.tzinfo is None
            or self.captured_at.utcoffset() is None
        ):
            raise ValueError("captured_at must be timezone-aware")
        if (
            not isinstance(self.bar_count, int)
            or isinstance(self.bar_count, bool)
            or self.bar_count < 1
        ):
            raise ValueError("bar_count must be a positive integer")
        for name in ("first_session", "last_session"):
            value = getattr(self, name)
            if not isinstance(value, date) or isinstance(value, datetime):
                raise ValueError(f"{name} must be a date")
        if self.first_session > self.last_session:
            raise ValueError("first_session must not follow last_session")


@dataclass(frozen=True)
class SwingObservation:
    kind: Literal["HIGH", "LOW"]
    pivot_index: int
    confirmation_index: int
    pivot_session: date
    confirmation_session: date
    price: float

    @property
    def key(self) -> tuple[str, int, int]:
        return self.kind, self.pivot_index, self.confirmation_index


@dataclass(frozen=True)
class ParityDifference:
    kind: DifferenceKind
    key: tuple[str, int, int]
    expected: SwingObservation | None
    observed: SwingObservation | None


@dataclass(frozen=True)
class SwingParityReport:
    python_count: int
    captured_count: int
    matched_count: int
    differences: tuple[ParityDifference, ...]
    snapshot_sha256: str
    study_sha256: str
    price_absolute_tolerance: float
    comparison_complete: bool
    platform_execution_verified: bool = False
    research_acceptance: str = "NOT_ESTABLISHED"


def _canonical_date(value: str, name: str) -> date:
    try:
        result = date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be ISO YYYY-MM-DD") from exc
    if result.isoformat() != value:
        raise ValueError(f"{name} must be canonical ISO YYYY-MM-DD")
    return result


def _index(value: str, name: str) -> int:
    if not value or not value.isascii() or not value.isdecimal():
        raise ValueError(f"{name} must be a nonnegative decimal index")
    return int(value)


def parse_swing_capture(csv_text: str) -> tuple[SwingObservation, ...]:
    """Parse the six exact CSV columns; reject duplicates and ambiguous records."""
    if not isinstance(csv_text, str):
        raise TypeError("csv_text must be a string")
    source = csv.DictReader(io.StringIO(csv_text, newline=""), strict=True)
    if source.fieldnames != list(_COLUMNS):
        raise ValueError("Capture requires exact ordered six-column CSV header")
    seen: set[tuple[str, int, int]] = set()
    result: list[SwingObservation] = []
    try:
        for record in source:
            if any(value is None for value in record.values()) or None in record:
                raise ValueError("Capture has missing or extra fields")
            kind = record["kind"]
            if kind not in ("HIGH", "LOW"):
                raise ValueError("Unsupported swing kind")
            pivot = _index(record["pivot_index"], "pivot_index")
            confirmation = _index(record["confirmation_index"], "confirmation_index")
            if confirmation <= pivot:
                raise ValueError("Confirmation index must be after pivot index")
            pivot_session = _canonical_date(record["pivot_session"], "pivot_session")
            confirmation_session = _canonical_date(
                record["confirmation_session"], "confirmation_session"
            )
            if confirmation_session <= pivot_session:
                raise ValueError("Confirmation session must follow pivot session")
            try:
                price = float(record["price"])
            except (TypeError, ValueError) as exc:
                raise ValueError("Invalid capture price") from exc
            if not math.isfinite(price) or price <= 0:
                raise ValueError("Capture price must be finite and positive")
            observation = SwingObservation(
                kind=kind,
                pivot_index=pivot,
                confirmation_index=confirmation,
                pivot_session=pivot_session,
                confirmation_session=confirmation_session,
                price=price,
            )
            if observation.key in seen:
                raise ValueError("Duplicate swing identity in capture")
            seen.add(observation.key)
            result.append(observation)
    except csv.Error as exc:
        raise ValueError("Malformed capture CSV") from exc
    return tuple(result)


def compare_swing_capture(
    dataset: OHLCVDataset,
    config: SwingConfig,
    captured_csv: str,
    *,
    capture: ThinkScriptCapture,
    study_source: bytes,
    price_absolute_tolerance: float = 1e-8,
) -> SwingParityReport:
    """Compare matched swing identities without asserting actual vendor execution.

    A capture that does not declare an identical normalized input snapshot,
    exact study bytes and chart length is rejected instead of silently aligned.
    """
    require_valid_dataset(dataset)
    if not isinstance(config, SwingConfig):
        raise TypeError("config must be a SwingConfig")
    if not isinstance(capture, ThinkScriptCapture):
        raise TypeError("capture must be ThinkScriptCapture")
    if not isinstance(study_source, bytes):
        raise TypeError("study_source must be bytes")
    if (
        isinstance(price_absolute_tolerance, bool)
        or not isinstance(price_absolute_tolerance, (int, float))
        or not math.isfinite(price_absolute_tolerance)
        or price_absolute_tolerance < 0
    ):
        raise ValueError("price_absolute_tolerance must be finite and nonnegative")
    bars = dataset.bars
    input_hash = sha256(canonical_json(dataset.to_dict()))
    study_hash = sha256(study_source)
    if (
        capture.symbol != bars[0].symbol
        or capture.bar_count != len(bars)
        or capture.first_session != bars[0].session
        or capture.last_session != bars[-1].session
        or capture.snapshot_sha256 != input_hash
        or capture.study_sha256 != study_hash
    ):
        raise ValueError("Capture source identity does not match requested comparison")

    expected = {
        (event.kind, event.pivot_index, event.confirmation_index): SwingObservation(
            kind=event.kind,
            pivot_index=event.pivot_index,
            confirmation_index=event.confirmation_index,
            pivot_session=event.pivot_session,
            confirmation_session=event.confirmation_session,
            price=event.price,
        )
        for event in confirmed_swings(dataset, config)
    }
    observed = {item.key: item for item in parse_swing_capture(captured_csv)}
    differences: list[ParityDifference] = []
    matched = 0
    for key in sorted(expected.keys() | observed.keys()):
        left = expected.get(key)
        right = observed.get(key)
        if left is None:
            reason: DifferenceKind = "EXTRA"
        elif right is None:
            reason = "MISSING"
        elif (left.pivot_session, left.confirmation_session) != (
            right.pivot_session,
            right.confirmation_session,
        ):
            reason = "SESSION_MISMATCH"
        elif not math.isclose(
            left.price, right.price, rel_tol=0.0, abs_tol=price_absolute_tolerance
        ):
            reason = "PRICE_MISMATCH"
        else:
            matched += 1
            continue
        differences.append(ParityDifference(reason, key, left, right))
    return SwingParityReport(
        python_count=len(expected),
        captured_count=len(observed),
        matched_count=matched,
        differences=tuple(differences),
        snapshot_sha256=input_hash,
        study_sha256=study_hash,
        price_absolute_tolerance=price_absolute_tolerance,
        comparison_complete=not differences,
    )
