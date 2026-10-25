"""Synthetic-only tests for fail-closed thinkorswim Strategy Report decoding."""

from __future__ import annotations

import pytest

from technical_engine.tos_report import merged_capture_csv, parse_swing_strategy_report

SESSIONS = (
    "2024-01-02",
    "2024-01-03",
    "2024-01-04",
    "2024-01-05",
    "2024-01-08",
    "2024-01-09",
    "2024-01-10",
    "2024-01-11",
    "2024-01-12",
)
HIGHS = (11, 12, 15.555, 13, 14, 13, 12, 10, 11)
LOWS = (8, 9, 10, 8.2, 7.25, 8.5, 9, 8, 9)
HEADER = "Id;Strategy;Side;Amount;Price;Date/Time;Trade P/L;P/L;Position;"


def report(
    kind="HIGH",
    pivot="20,240,104",
    confirm="20,240,108",
    price="15.555",
    trade_date="1/9/24",
    side="Buy to Open",
    symbol="TEST",
    name=None,
):
    if name is None:
        name = f"TAE_Swing_Event_Export(TAE_EVT|{kind}|{pivot}|{confirm}|{price})"
    return (
        f"Strategy report\nSymbol: {symbol}\nWork Time: synthetic\n\n\n{HEADER}\n"
        f"2;{name};{side};1.0;$1.00;{trade_date};;$0.00;0.0;\n"
        "3;TAE_Swing_Event_Export(ExportExit);Sell to Close;-1.0;$1.00;1/10/24;;$0.00;0.0;\n"
    ).encode()


def parse(raw, kind="HIGH", sessions=SESSIONS, prices=None):
    if prices is None:
        prices = HIGHS if kind == "HIGH" else LOWS
    return parse_swing_strategy_report(
        raw,
        symbol="TEST",
        expected_kind=kind,
        sessions=sessions,
        pivot_prices=prices,
        right_bars=2,
    )


def test_valid_high_and_low_merge_exact_columns_and_subcent_price():
    high = parse(report())
    low = parse(
        report(
            kind="LOW",
            pivot="20,240,108",
            confirm="20,240,110",
            price="7.25",
            trade_date="1/11/24",
            side="Buyto Open",
        ),
        kind="LOW",
    )
    assert len(high.events) == len(low.events) == 1
    assert not high.warnings and not low.warnings
    assert high.events[0].csv_row() == ("HIGH", 2, 4, "2024-01-04", "2024-01-08", "15.555")
    capture = merged_capture_csv(high, low)
    assert capture.splitlines() == [
        "kind,pivot_index,confirmation_index,pivot_session,confirmation_session,price",
        "HIGH,2,4,2024-01-04,2024-01-08,15.555",
        "LOW,4,6,2024-01-08,2024-01-10,7.25",
    ]


def test_synthetic_same_confirmation_high_low_are_preserved():
    high = parse(report())
    low = parse(report(kind="LOW", price="10"), kind="LOW")
    capture = merged_capture_csv(high, low)
    assert len(capture.splitlines()) == 3


def test_pivot_price_discrepancy_is_preserved_and_warned():
    parsed = parse(report(price="15.554"))
    assert parsed.events[0].price_text == "15.554"
    assert len(parsed.warnings) == 1
    assert "PRICE_MISMATCH" in parsed.warnings[0]


@pytest.mark.parametrize(
    ("source", "error"),
    [
        (lambda: report(symbol="WRONG"), "symbol"),
        (lambda: report().replace(HEADER.encode(), b"Id;Wrong"), "header"),
        (lambda: report(kind="LOW"), "Wrong export pass"),
        (lambda: report(side="Sell to Open"), "entry side"),
        (lambda: report(pivot="20241350"), "date"),
        (lambda: report(pivot="20240101"), "outside frozen"),
        (lambda: report(confirm="20240109", trade_date="1/10/24"), "offset"),
        (lambda: report(trade_date="1/10/24"), "trade date mismatch"),
        (lambda: report(price="0"), "signal price"),
        (lambda: report(name="TAE_Swing_Event_Export(Unrecognized)"), "label"),
        (lambda: report().replace(b";0.0;\n", b";0.0;EXTRA;\n"), "columns"),
        (lambda: report() + report().splitlines()[6] + b"\n", "Duplicate signal"),
        (lambda: b"", "title"),
    ],
)
def test_malformed_reports_fail_closed(source, error):
    with pytest.raises(ValueError, match=error):
        parse(source())


def test_out_of_order_or_duplicate_snapshot_sessions_rejected():
    for sessions in (SESSIONS[:3] + SESSIONS[2:], tuple(reversed(SESSIONS))):
        with pytest.raises(ValueError, match="Sessions"):
            parse(report(), sessions=sessions)


def test_final_confirmation_bar_cannot_claim_next_trade_date():
    short = SESSIONS[:5]
    with pytest.raises(ValueError, match="last session"):
        parse(report(), sessions=short, prices=HIGHS[:5])


def test_missing_report_observation_cannot_be_inferred():
    high = parse(report())
    assert len(high.events) == 1
    capture = merged_capture_csv(
        high,
        parse(
            report(
                kind="LOW",
                pivot="20,240,108",
                confirm="20,240,110",
                price="7.25",
                trade_date="1/11/24",
            ),
            kind="LOW",
        ),
    )
    assert "LOW," not in capture.splitlines()[1]
