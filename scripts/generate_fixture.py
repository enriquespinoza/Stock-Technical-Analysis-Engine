"""Generate deterministic synthetic daily bars; this is not market data.

Usage: python scripts/generate_fixture.py --output data/synthetic.json
"""

from __future__ import annotations

import argparse
import math
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from technical_engine.artifacts import canonical_json
from technical_engine.data import OHLCVBar, OHLCVDataset


def make_fixture(count: int = 280) -> OHLCVDataset:
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ValueError("count must be a positive integer")
    bars = []
    session = date(2023, 1, 2)
    retrieved_at = datetime(2025, 1, 1, tzinfo=UTC)
    for index in range(count):
        while session.weekday() >= 5:
            session += timedelta(days=1)
        close = round(100 + 0.08 * index + 2.0 * math.sin(index / 7.0), 6)
        open_price = round(close + 0.3 * math.cos(index / 4.0), 6)
        available_at = datetime.combine(session, time(22, 0), tzinfo=UTC)
        if available_at > retrieved_at:
            raise ValueError("Fixture count exceeds the fixed retrieval timestamp")
        bars.append(
            OHLCVBar(
                symbol="SYNTH",
                session=session,
                open=open_price,
                high=max(open_price, close) + 0.8,
                low=min(open_price, close) - 0.7,
                close=close,
                volume=float(100_000 + (index % 13) * 2100),
                provider="synthetic-fixture",
                retrieved_at=retrieved_at,
                available_at=available_at,
                adjustment_policy="unadjusted",
                snapshot_id="synthetic-daily-v1",
                corporate_actions=(),
                quality_status="valid",
            )
        )
        session += timedelta(days=1)
    return OHLCVDataset(bars=tuple(bars), snapshot_id="synthetic-daily-v1")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a deterministic synthetic OHLCV fixture")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, default=280)
    args = parser.parse_args()
    content = canonical_json(make_fixture(args.count).to_dict())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Exact reruns are safe; preserve any different preexisting input snapshot.
    try:
        with args.output.open("xb") as stream:
            stream.write(content)
    except FileExistsError:
        if args.output.is_symlink() or args.output.read_bytes() != content:
            parser.exit(2, f"Refusing to overwrite existing snapshot: {args.output}\n")
    print(args.output)


if __name__ == "__main__":
    main()
