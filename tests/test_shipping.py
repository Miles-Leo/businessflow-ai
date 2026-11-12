from datetime import datetime, timedelta, timezone, tzinfo

import pytest
from app.services.shipping import is_overdue_unshipped, assess_order_shipping
from copy import deepcopy


PROMISED = datetime(2026, 10, 2, 8, tzinfo=timezone.utc)


@pytest.mark.parametrize("shipped,checked,expected", [
    (None, PROMISED + timedelta(seconds=1), True),
    (None, PROMISED, False),
    (None, PROMISED - timedelta(seconds=1), False),
    (PROMISED - timedelta(hours=1), PROMISED + timedelta(days=1), False),
    (PROMISED + timedelta(hours=1), PROMISED + timedelta(days=1), False),
])
def test_overdue_unshipped_boundaries(shipped, checked, expected):
    assert is_overdue_unshipped(PROMISED, shipped, checked) is expected


def test_different_timezones_same_instant_is_not_overdue():
    checked = datetime(2026, 10, 2, 16, tzinfo=timezone(timedelta(hours=8)))
    assert is_overdue_unshipped(PROMISED, None, checked) is False


class MissingOffset(tzinfo):
    def utcoffset(self, dt):
        return None


@pytest.mark.parametrize("field", ["promised_ship_at", "shipped_at", "checked_at"])
@pytest.mark.parametrize("zone", [None, MissingOffset()])
def test_rejects_time_without_valid_offset(field, zone):
    arguments = {
        "promised_ship_at": PROMISED,
        "shipped_at": PROMISED,
        "checked_at": PROMISED + timedelta(days=1),
    }
    arguments[field] = PROMISED.replace(tzinfo=zone)
    with pytest.raises(ValueError, match="时区"):
        is_overdue_unshipped(**arguments)


@pytest.mark.parametrize("status,shipped,expected", [
    ("pending", None, True),
    ("shipped", "2026-10-02T07:00:00Z", False),
    ("shipped", "2026-10-03T08:00:00Z", False),
])
def test_assessment_returns_serializable_result_without_mutation(status, shipped, expected):
    order = {"order_id": "BF2026001", "promised_ship_at": "2026-10-02T08:00:00Z",
             "shipped_at": shipped, "status": status}
    original = deepcopy(order)
    checked = datetime(2026, 11, 7, 8, tzinfo=timezone.utc)
    assert assess_order_shipping(order, checked) == {
        "order_id": "BF2026001", "checked_at": checked.isoformat(),
        "is_overdue_unshipped": expected,
    }
    assert order == original


@pytest.mark.parametrize("shipped,expected_error", [
    (None, "发货时间"),
    ("2026-11-08T08:00:00Z", "晚于查询时刻"),
])
def test_assessment_rejects_conflicting_data(shipped, expected_error):
    order = {"order_id": "BF2026001", "promised_ship_at": "2026-10-02T08:00:00Z",
             "shipped_at": shipped, "status": "shipped"}
    with pytest.raises(ValueError, match=expected_error):
        assess_order_shipping(order, datetime(2026, 11, 7, 8, tzinfo=timezone.utc))


@pytest.mark.parametrize("field", ["promised_ship_at", "shipped_at", "checked_at"])
def test_assessment_validates_timezone_before_comparison(field):
    order = {"order_id": "BF2026001", "promised_ship_at": "2026-10-02T08:00:00Z",
             "shipped_at": "2026-10-03T08:00:00Z", "status": "shipped"}
    checked = datetime(2026, 11, 7, 8, tzinfo=timezone.utc)
    if field == "checked_at":
        checked = checked.replace(tzinfo=None)
    else:
        order[field] = order[field].removesuffix("Z")
    with pytest.raises(ValueError, match="时区"):
        assess_order_shipping(order, checked)


def test_assessment_shipping_at_check_time_is_valid():
    order = {"order_id": "BF2026001", "promised_ship_at": "2026-10-02T08:00:00Z",
             "shipped_at": "2026-10-03T08:00:00Z", "status": "shipped"}
    checked = datetime(2026, 10, 3, 8, tzinfo=timezone.utc)
    assert assess_order_shipping(order, checked)["is_overdue_unshipped"] is False


@pytest.mark.parametrize("missing_field", ["order_id", "promised_ship_at", "shipped_at", "status"])
def test_assessment_reports_missing_field(missing_field):
    order = {"order_id": "BF2026001", "promised_ship_at": "2026-10-02T08:00:00Z",
             "shipped_at": None, "status": "pending"}
    del order[missing_field]
    with pytest.raises(ValueError, match=missing_field):
        assess_order_shipping(order, datetime(2026, 11, 7, 8, tzinfo=timezone.utc))


def test_explicit_null_shipped_at_is_not_missing():
    order = {"order_id": "BF2026001", "promised_ship_at": "2026-10-02T08:00:00Z",
             "shipped_at": None, "status": "pending"}
    assert assess_order_shipping(
        order, datetime(2026, 11, 7, 8, tzinfo=timezone.utc)
    )["is_overdue_unshipped"] is True


@pytest.mark.parametrize("field,value", [
    ("promised_ship_at", None),
    ("promised_ship_at", 123),
    ("promised_ship_at", "不是日期"),
    ("promised_ship_at", ""),
    ("shipped_at", 123),
    ("shipped_at", "不是日期"),
    ("shipped_at", ""),
])
def test_assessment_reports_invalid_time_field(field, value):
    order = {"order_id": "BF2026001", "promised_ship_at": "2026-10-02T08:00:00Z",
             "shipped_at": None, "status": "pending"}
    order[field] = value
    with pytest.raises(ValueError, match=field):
        assess_order_shipping(order, datetime(2026, 11, 7, 8, tzinfo=timezone.utc))
