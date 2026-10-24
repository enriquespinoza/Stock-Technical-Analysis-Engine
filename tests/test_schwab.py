"""Offline Schwab normalization; supplied metadata is never inferred."""

import copy
from datetime import UTC, date, datetime

import pytest

from technical_engine.data import CorporateAction
from technical_engine.providers.schwab import normalize_price_history


def payload():
    return {
        "symbol": "TEST",
        "empty": False,
        "candles": [
            {
                "datetime": int(datetime(2024, 1, 3, 1, tzinfo=UTC).timestamp() * 1000),
                "open": 100.0,
                "high": 105.0,
                "low": 98.0,
                "close": 103.0,
                "volume": 1000,
            }
        ],
    }


def normalize(source, **changes):
    options = {
        "retrieved_at": datetime(2024, 2, 1, tzinfo=UTC),
        "available_at": datetime(2024, 2, 1, tzinfo=UTC),
        "adjustment_policy": "provider_reported_unadjusted",
        "snapshot_id": "fixture-schwab",
        "session_timezone": "America/New_York",
    }
    options.update(changes)
    return normalize_price_history(source, **options)


def test_normalization_uses_explicit_timezone_and_retains_provenance():
    source = payload()
    before = copy.deepcopy(source)
    normalized = normalize(source)
    assert source == before
    assert normalized.bars[0].session == date(2024, 1, 2)
    assert normalized.bars[0].provider == "schwab"
    assert normalized.bars[0].snapshot_id == "fixture-schwab"
    assert normalized.bars[0].adjustment_policy == "provider_reported_unadjusted"
    assert normalized.bars[0].retrieved_at == datetime(2024, 2, 1, tzinfo=UTC)
    assert normalized.bars[0].available_at == normalized.bars[0].retrieved_at
    assert normalize(source, session_timezone="UTC").bars[0].session == date(2024, 1, 3)


def test_explicit_action_metadata_preserved_without_adjusting_prices():
    action = CorporateAction(
        action_type="split",
        ex_date=date(2024, 1, 2),
        adjustment_factor=0.5,
        available_at=datetime(2024, 1, 1, tzinfo=UTC),
    )
    normalized = normalize(payload(), corporate_actions=(action,))
    assert normalized.bars[0].corporate_actions == (action,)
    assert normalized.bars[0].close == 103.0


@pytest.mark.parametrize("field", ["datetime", "open", "high", "low", "close", "volume"])
def test_missing_candle_fields_rejected(field):
    source = payload()
    del source["candles"][0][field]
    with pytest.raises(ValueError, match="missing required"):
        normalize(source)


@pytest.mark.parametrize(
    "value", [None, "1704243600000", True, float("nan"), float("inf"), 10**400]
)
def test_invalid_epoch_timestamp(value):
    source = payload()
    source["candles"][0]["datetime"] = value
    with pytest.raises(ValueError, match="datetime"):
        normalize(source)


@pytest.mark.parametrize(
    "source",
    [
        {},
        {"symbol": "", "candles": []},
        {"symbol": "TEST", "candles": None},
        {"symbol": "TEST", "candles": [None]},
        [],
    ],
)
def test_malformed_response(source):
    with pytest.raises(ValueError):
        normalize(source)


def test_empty_unsorted_duplicate_and_invalid_candles_are_not_repaired():
    source = payload()
    source["candles"] = []
    with pytest.raises(ValueError, match="Insufficient history"):
        normalize(source)
    source = payload()
    source["candles"].append(copy.deepcopy(source["candles"][0]))
    with pytest.raises(ValueError, match="Duplicate trading sessions"):
        normalize(source)
    source["candles"][1]["datetime"] -= 24 * 60 * 60 * 1000
    with pytest.raises(ValueError, match="strictly increasing"):
        normalize(source)
    source = payload()
    source["candles"][0]["low"] = None
    with pytest.raises(ValueError, match="low must be finite"):
        normalize(source)


def test_all_provenance_inputs_are_required():
    with pytest.raises(TypeError):
        normalize_price_history(payload())
