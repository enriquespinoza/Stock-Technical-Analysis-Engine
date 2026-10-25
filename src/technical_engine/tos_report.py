"""Strict, research-only decoding of thinkorswim swing Strategy Reports.

Reports are operator-supplied observations, not vendor-attested execution.
The parser never calculates signals or repairs malformed source records.
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

SwingKind = Literal["HIGH", "LOW"]
_REPORT_HEADER = (
    "Id;Strategy;Side;Amount;Price;Date/Time;Trade P/L;P/L;Position;"
)
_EVENT = re.compile(
    r"TAE_Swing_Event_Export\(TAE_EVT\|(HIGH|LOW)\|"
    r"(\d{8}|\d{2},\d{3},\d{3})\|"
    r"(\d{8}|\d{2},\d{3},\d{3})\|"
    r"(\d+(?:\.\d+)?|\.\d+)\)"
)
_EXIT = "TAE_Swing_Event_Export(ExportExit)"
_FIELDS = (
    "kind", "pivot_index", "confirmation_index", "pivot_session", "confirmation_session", "price"
)


@dataclass(frozen=True)
class ReportEvent:
    kind: SwingKind
    pivot_index: int
    confirmation_index: int
    pivot_session: str
    confirmation_session: str
    price_text: str
    source_line: int

    def csv_row(self) -> tuple[str, int, int, str, str, str]:
        return (
            self.kind, self.pivot_index, self.confirmation_index,
            self.pivot_session, self.confirmation_session, self.price_text,
        )


@dataclass(frozen=True)
class ParsedReport:
    events: tuple[ReportEvent, ...]
    report_sha256: str
    warnings: tuple[str, ...]


def _decode_date(value: str) -> str:
    digits = value.replace(",", "")
    try:
        parsed = datetime.strptime(digits, "%Y%m%d").date()
    except ValueError as exc:
        raise ValueError(f"Invalid encoded event date: {value}") from exc
    if parsed.strftime("%Y%m%d") != digits:
        raise ValueError(f"Invalid encoded event date: {value}")
    return parsed.isoformat()


def _session_index(sessions: Sequence[str]) -> dict[str, int]:
    if not sessions:
        raise ValueError("Empty session sequence")
    lookup = {}
    previous = None
    for index, session in enumerate(sessions):
        try:
            parsed = date.fromisoformat(session)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid session at index {index}") from exc
        if parsed.isoformat() != session or (previous is not None and parsed <= previous):
            raise ValueError("Sessions must be canonical, unique, and increasing")
        lookup[session] = index
        previous = parsed
    return lookup


def parse_swing_strategy_report(
    raw: bytes,
    *,
    symbol: str,
    expected_kind: SwingKind,
    sessions: Sequence[str],
    pivot_prices: Sequence[float],
    right_bars: int = 2,
) -> ParsedReport:
    """Decode one HIGH or LOW pass against a frozen daily session sequence.

    Trade dates must be the following *observed session*. A signal confirmed
    on the last snapshot bar cannot be validated from a next-bar order and
    fails closed if present. Absence of such a signal is NOT proof of absence;
    the separate Python comparator must check completeness.
    """
    if not isinstance(raw, bytes):
        raise TypeError("Report must be raw bytes")
    if not symbol or expected_kind not in ("HIGH", "LOW"):
        raise ValueError("Invalid symbol or kind")
    if isinstance(right_bars, bool) or not isinstance(right_bars, int) or right_bars < 1:
        raise ValueError("right_bars must be a positive integer")
    lookup = _session_index(sessions)
    if len(pivot_prices) != len(sessions):
        raise ValueError("Pivot price count does not match session count")
    try:
        lines = raw.decode("utf-8-sig").splitlines()
    except UnicodeDecodeError as exc:
        raise ValueError("Report must be UTF-8") from exc
    if len(lines) < 6 or lines[0].strip() != "Strategy report":
        raise ValueError("Missing Strategy Report title")
    if lines[1].strip() != f"Symbol: {symbol}":
        raise ValueError("Report symbol does not match requested symbol")
    headers = [i for i, line in enumerate(lines) if line.strip() == _REPORT_HEADER]
    if len(headers) != 1:
        raise ValueError("Expected exactly one recognized Strategy Report header")
    first_row = headers[0] + 1
    seen = set()
    events = []
    warnings = []
    for line_idx in range(first_row, len(lines)):
        line = lines[line_idx].strip()
        if not line:
            continue
        # Permit non-trade footer text but never silently discard event labels.
        if not re.match(r"^\d+;", line):
            if "TAE_EVT|" in line:
                raise ValueError(f"Unrecognized event record on line {line_idx + 1}")
            continue
        try:
            fields = next(csv.reader([line], delimiter=";", strict=True))
        except csv.Error as exc:
            raise ValueError(f"Malformed report CSV on line {line_idx + 1}") from exc
        if len(fields) != 10 or fields[-1] != "":
            raise ValueError(f"Incorrect trade columns on line {line_idx + 1}")
        name = fields[1].strip()
        if name == _EXIT:
            if "".join(fields[2].lower().split()) != "selltoclose":
                raise ValueError(f"Invalid exit side on line {line_idx + 1}")
            continue
        match = _EVENT.fullmatch(name)
        if match is None:
            raise ValueError(f"Unknown or malformed strategy label on line {line_idx + 1}")
        kind, pivot_raw, confirm_raw, price_text = match.groups()
        if kind != expected_kind:
            raise ValueError(f"Wrong export pass on line {line_idx + 1}")
        if "".join(fields[2].lower().split()) != "buytoopen":
            raise ValueError(f"Invalid entry side on line {line_idx + 1}")
        pivot = _decode_date(pivot_raw)
        confirmation = _decode_date(confirm_raw)
        if pivot not in lookup or confirmation not in lookup:
            raise ValueError(f"Event date outside frozen sessions on line {line_idx + 1}")
        pi, ci = lookup[pivot], lookup[confirmation]
        if ci - pi != right_bars:
            raise ValueError(f"Incorrect confirmation bar offset on line {line_idx + 1}")
        if ci + 1 >= len(sessions):
            raise ValueError(f"Cannot verify next-bar trade date on last session (line {line_idx + 1})")
        try:
            report_date = datetime.strptime(fields[5].strip(), "%m/%d/%y").date().isoformat()
        except ValueError as exc:
            raise ValueError(f"Malformed report trade date on line {line_idx + 1}") from exc
        if report_date != sessions[ci + 1]:
            raise ValueError(f"Next-bar trade date mismatch on line {line_idx + 1}")
        price = float(price_text)
        if not math.isfinite(price) or price <= 0:
            raise ValueError(f"Invalid signal price on line {line_idx + 1}")
        key = (kind, pi, ci)
        if key in seen:
            raise ValueError(f"Duplicate signal on line {line_idx + 1}")
        seen.add(key)
        expected_price = pivot_prices[pi]
        if not isinstance(expected_price, (int, float)) or not math.isfinite(expected_price):
            raise ValueError(f"Invalid reference pivot price for index {pi}")
        if not math.isclose(price, expected_price, rel_tol=0.0, abs_tol=1e-8):
            warnings.append(
                f"PRICE_MISMATCH {kind} pivot={pivot} observed={price_text} "
                f"snapshot={expected_price}"
            )
        events.append(ReportEvent(kind, pi, ci, pivot, confirmation, price_text, line_idx + 1))
    if not events:
        raise ValueError(f"No {expected_kind} events in report")
    return ParsedReport(tuple(events), hashlib.sha256(raw).hexdigest(), tuple(warnings))


def merged_capture_csv(highs: ParsedReport, lows: ParsedReport) -> str:
    """Build the exact six-column capture from independently decoded passes."""
    seen = set()
    events = []
    for report in (highs, lows):
        for event in report.events:
            key = (event.kind, event.pivot_index, event.confirmation_index)
            if key in seen:
                raise ValueError(f"Duplicate event across reports: {key}")
            seen.add(key)
            events.append(event)
    events.sort(key=lambda item: (item.confirmation_index, item.kind, item.pivot_index))
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(_FIELDS)
    writer.writerows(event.csv_row() for event in events)
    return stream.getvalue()
