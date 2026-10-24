"""Contract checks independent of providers and analytical calculations."""

import copy
import json
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from technical_engine.data import (
    CorporateAction,
    OHLCVBar,
    OHLCVDataset,
    require_valid_dataset,
    validate_dataset,
)


def bar(**changes):
    source = OHLCVBar(
        symbol="TEST",
        session=date(2024, 1, 2),
        open=100.0,
        high=105.0,
        low=98.0,
        close=103.0,
        volume=1000.0,
        provider="fixture",
        retrieved_at=datetime(2024, 2, 1, tzinfo=UTC),
        available_at=datetime(2024, 1, 2, 21, tzinfo=UTC),
        adjustment_policy="unadjusted",
        snapshot_id="test-snapshot",
    )
    return replace(source, **changes)


def dataset(*bars):
    return OHLCVDataset(bars=tuple(bars) if bars else (bar(),), snapshot_id="test-snapshot")


def test_valid_dataset_is_immutable_and_validation_does_not_mutate():
    source = dataset(
        bar(), bar(session=date(2024, 1, 3), available_at=datetime(2024, 1, 3, 21, tzinfo=UTC))
    )
    before = copy.deepcopy(source)
    report = require_valid_dataset(source, expected_sessions=[date(2024, 1, 2), date(2024, 1, 3)])
    assert source == before
    assert report.is_valid
    assert report.errors == report.warnings == ()
    assert report.to_dict()["row_count"] == 2
    with pytest.raises(FrozenInstanceError):
        source.bars[0].close = 10
    with pytest.raises(FrozenInstanceError):
        source.snapshot_id = "changed"


@pytest.mark.parametrize("field", ["open", "high", "low", "close"])
@pytest.mark.parametrize(
    "value", [0, -1, float("nan"), float("inf"), -float("inf"), None, True, "100", 10**400]
)
def test_invalid_prices_are_rejected(field, value):
    source = dataset(bar(**{field: value}))
    assert not validate_dataset(source).is_valid
    with pytest.raises(ValueError, match=field):
        require_valid_dataset(source)


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), None, True, "100", 10**400])
def test_invalid_volume_is_rejected(value):
    with pytest.raises(ValueError, match="volume"):
        require_valid_dataset(dataset(bar(volume=value)))


def test_zero_volume_is_allowed_but_flagged():
    report = require_valid_dataset(dataset(bar(volume=0)))
    assert any("zero volume" in warning for warning in report.warnings)


@pytest.mark.parametrize("changes", [{"high": 99}, {"low": 104}, {"open": 106}, {"close": 97}])
def test_invalid_ohlc_relationships(changes):
    with pytest.raises(ValueError, match="OHLC relationships"):
        require_valid_dataset(dataset(bar(**changes)))


@pytest.mark.parametrize("field", ["available_at", "retrieved_at"])
@pytest.mark.parametrize("value", [None, "2024-01-02", datetime(2024, 1, 2)])
def test_missing_or_naive_timestamps(field, value):
    with pytest.raises(ValueError, match="timezone-aware"):
        require_valid_dataset(dataset(bar(**{field: value})))


def test_availability_cannot_follow_snapshot_capture_or_precede_session():
    with pytest.raises(ValueError, match="later than retrieved_at"):
        require_valid_dataset(dataset(bar(available_at=datetime(2025, 1, 1, tzinfo=UTC))))
    with pytest.raises(ValueError, match="precedes the earliest possible session start"):
        require_valid_dataset(dataset(bar(available_at=datetime(2023, 1, 1, tzinfo=UTC))))


def test_availability_uses_actual_instants_with_timezone_offsets():
    source = dataset(
        bar(
            retrieved_at=datetime(2024, 1, 2, 16, tzinfo=timezone(timedelta(hours=-5))),
            available_at=datetime(2024, 1, 2, 21, tzinfo=UTC),
        )
    )
    assert require_valid_dataset(source).is_valid


@pytest.mark.parametrize("offset", [-12, -5, 0, 12, 14])
def test_cross_date_timestamp_representation_does_not_change_availability_validity(offset):
    # A January 2 exchange session may close early enough to be January 1 in a
    # different timestamp representation. The session has no attached timezone.
    available = datetime(2024, 1, 2, 4, tzinfo=UTC).astimezone(timezone(timedelta(hours=offset)))
    assert require_valid_dataset(dataset(bar(available_at=available))).is_valid


@pytest.mark.parametrize("offset", [-12, 0, 14])
def test_impossible_availability_before_any_session_start_rejected_at_all_offsets(offset):
    # January 2 at midnight UTC+14 is January 1 at 10:00 UTC, the broad lower bound.
    unavailable = datetime(2024, 1, 1, 9, 59, tzinfo=UTC).astimezone(
        timezone(timedelta(hours=offset))
    )
    with pytest.raises(ValueError, match="earliest possible session start"):
        require_valid_dataset(dataset(bar(available_at=unavailable)))


def test_previous_utc_date_is_permitted_at_conservative_session_start_bound():
    available = datetime(2024, 1, 1, 10, tzinfo=UTC)
    assert require_valid_dataset(dataset(bar(available_at=available))).is_valid


@pytest.mark.parametrize("session", [None, "2024-01-02", datetime(2024, 1, 2, tzinfo=UTC)])
def test_session_requires_date_not_datetime(session):
    with pytest.raises(ValueError, match="session must be a date"):
        require_valid_dataset(dataset(bar(session=session)))


def test_unsorted_and_duplicate_sessions_rejected_without_repair():
    earlier = bar()
    later = bar(session=date(2024, 1, 3), available_at=datetime(2024, 1, 3, 21, tzinfo=UTC))
    source = dataset(later, earlier)
    with pytest.raises(ValueError, match="strictly increasing"):
        require_valid_dataset(source)
    assert source.bars == (later, earlier)
    with pytest.raises(ValueError, match="Duplicate trading sessions"):
        require_valid_dataset(dataset(earlier, earlier))


def test_history_requirements_and_missing_sessions():
    with pytest.raises(ValueError, match="Insufficient history"):
        require_valid_dataset(OHLCVDataset(bars=(), snapshot_id="test-snapshot"))
    with pytest.raises(ValueError, match="Insufficient history"):
        require_valid_dataset(dataset(), min_history=2)
    with pytest.raises(ValueError, match="Missing expected sessions"):
        require_valid_dataset(dataset(), expected_sessions=[date(2024, 1, 2), date(2024, 1, 3)])
    with pytest.raises(ValueError, match="Unexpected sessions"):
        require_valid_dataset(dataset(), expected_sessions=[])
    assert any(
        "Calendar completeness not assessed" in item
        for item in validate_dataset(dataset()).warnings
    )


@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_invalid_min_history(value):
    with pytest.raises(ValueError, match="min_history"):
        validate_dataset(dataset(), min_history=value)


@pytest.mark.parametrize("field", ["symbol", "provider", "adjustment_policy", "snapshot_id"])
@pytest.mark.parametrize("value", [None, "", "  ", 123])
def test_required_metadata(field, value):
    with pytest.raises(ValueError, match=field):
        require_valid_dataset(dataset(bar(**{field: value})))


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("symbol", "OTHER", "multiple symbols"),
        ("provider", "other", "multiple providers"),
        ("adjustment_policy", "split_adjusted", "multiple adjustment policies"),
        ("snapshot_id", "other", "differs from dataset"),
    ],
)
def test_mixed_provenance_rejected(field, value, reason):
    second = bar(
        session=date(2024, 1, 3),
        available_at=datetime(2024, 1, 3, 21, tzinfo=UTC),
        **{field: value},
    )
    with pytest.raises(ValueError, match=reason):
        require_valid_dataset(dataset(bar(), second))


def test_quality_status_and_immutability_enforced():
    report = require_valid_dataset(dataset(bar(quality_status="suspect")))
    assert any("suspect" in item for item in report.warnings)
    with pytest.raises(ValueError, match="marked invalid"):
        require_valid_dataset(dataset(bar(quality_status="invalid")))
    with pytest.raises(ValueError, match="unsupported quality_status"):
        require_valid_dataset(dataset(bar(quality_status="missing")))
    with pytest.raises(ValueError, match="immutable tuple"):
        require_valid_dataset(OHLCVDataset(bars=[bar()], snapshot_id="test-snapshot"))


def test_structured_corporate_action_round_trip():
    action = CorporateAction(
        action_type="split",
        ex_date=date(2024, 1, 2),
        adjustment_factor=0.5,
        available_at=datetime(2023, 12, 28, 12, tzinfo=UTC),
        status="confirmed",
        details="Two-for-one split; factor supplied by fixture provider",
    )
    source = dataset(bar(corporate_actions=(action,)))
    serialized = json.dumps(source.to_dict(), sort_keys=True, allow_nan=False)
    restored = OHLCVDataset.from_dict(json.loads(serialized))
    assert restored == source
    assert restored.to_dict() == source.to_dict()
    assert source.bars[0].close == 103.0  # No automatic factor application.


def test_unknown_and_future_corporate_action_availability():
    unknown = CorporateAction(
        action_type="dividend", ex_date=date(2024, 1, 2), amount=0.5, currency="USD"
    )
    report = require_valid_dataset(dataset(bar(corporate_actions=(unknown,))))
    assert any("metadata availability is unknown" in item for item in report.warnings)
    future = replace(unknown, available_at=datetime(2024, 1, 3, 12, tzinfo=UTC))
    with pytest.raises(ValueError, match="metadata available after"):
        require_valid_dataset(dataset(bar(corporate_actions=(future,))))


@pytest.mark.parametrize(
    "change",
    [
        {"adjustment_factor": 0},
        {"adjustment_factor": float("inf")},
        {"amount": -1},
        {"amount": True},
        {"currency": ""},
        {"action_type": ""},
        {"status": None},
        {"ex_date": None},
        {"available_at": datetime(2024, 1, 1)},
        {"details": 10},
    ],
)
def test_malformed_corporate_action_metadata(change):
    action = replace(CorporateAction(action_type="split", ex_date=date(2024, 1, 2)), **change)
    with pytest.raises(ValueError, match="corporate action"):
        require_valid_dataset(dataset(bar(corporate_actions=(action,))))


def test_plain_label_is_not_structured_corporate_action_metadata():
    with pytest.raises(ValueError, match="must be a CorporateAction"):
        require_valid_dataset(dataset(bar(corporate_actions=("split",))))


def test_serialization_strictness_and_no_missing_timestamps():
    source = dataset().to_dict()
    assert OHLCVDataset.from_dict(source).to_dict() == source
    variants = []
    for key in ("snapshot_id", "bars", "schema_version"):
        modified = copy.deepcopy(source)
        del modified[key]
        variants.append(modified)
    modified = copy.deepcopy(source)
    modified["schema_version"] = "future"
    variants.append(modified)
    for key in ("retrieved_at", "available_at", "session"):
        modified = copy.deepcopy(source)
        modified["bars"][0][key] = None
        variants.append(modified)
    modified = copy.deepcopy(source)
    modified["bars"][0]["retrieved_at"] = "2024-01-02T21:00:00"
    variants.append(modified)
    modified = copy.deepcopy(source)
    modified["bars"][0]["close"] = "103"
    variants.append(modified)
    modified = copy.deepcopy(source)
    modified["bars"][0]["unknown"] = "no silent drop"
    variants.append(modified)
    for invalid in variants + [[], None, "not a mapping"]:
        with pytest.raises(ValueError):
            OHLCVDataset.from_dict(invalid)


def test_expected_calendar_requires_dates():
    with pytest.raises(ValueError, match="expected_sessions"):
        validate_dataset(dataset(), expected_sessions=["2024-01-02"])
