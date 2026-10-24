"""Offline command-line feature generation from an explicit input snapshot."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from technical_engine.artifacts import generate_artifacts
from technical_engine.data import OHLCVDataset
from technical_engine.indicators import IndicatorConfig


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ValueError(f"Nonfinite JSON number: {value}")


def _load_json(raw: bytes) -> Any:
    return json.loads(raw, object_pairs_hook=_object, parse_constant=_invalid_constant)


def _timestamp(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use an ISO-8601 timestamp with a timezone") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise argparse.ArgumentTypeError("--run-at requires an explicit timezone")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate immutable research-only technical features offline"
    )
    parser.add_argument("--input", type=Path, required=True, help="Normalized OHLCV snapshot JSON")
    parser.add_argument(
        "--output", type=Path, required=True, help="Root containing immutable run directories"
    )
    parser.add_argument(
        "--run-at", type=_timestamp, required=True, help="Explicit aware ISO-8601 run timestamp"
    )
    parser.add_argument("--config", type=Path, help="Versioned indicator configuration JSON")
    args = parser.parse_args(argv)
    try:
        raw = args.input.read_bytes()
        dataset = OHLCVDataset.from_dict(_load_json(raw))
        config = (
            IndicatorConfig.from_dict(_load_json(args.config.read_bytes()))
            if args.config is not None
            else IndicatorConfig()
        )
        run = generate_artifacts(
            dataset, args.output, run_at=args.run_at, config=config, raw_input=raw
        )
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(2, f"technical-engine: {exc}\n")
    print(run.directory)
    return 0
