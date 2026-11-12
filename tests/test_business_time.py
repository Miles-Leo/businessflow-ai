from datetime import datetime, timezone
import pytest
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import text
from app.core.time import business_iso, business_display
from app.schemas.time import BusinessDateTime


@pytest.mark.parametrize("value,expected", [
    ("2026-11-09T08:00:00Z", "2026-11-09T16:00:00+08:00"),
    ("2026-11-09T20:00:00Z", "2026-11-10T04:00:00+08:00"),
    ("2026-11-09T16:00:00+08:00", "2026-11-09T16:00:00+08:00"),
    ("2026-11-09T01:00:00-07:00", "2026-11-09T16:00:00+08:00"),
])
def test_conversion_preserves_instant(value, expected):
    assert business_iso(value) == expected
    assert datetime.fromisoformat(value) == datetime.fromisoformat(expected)


def test_naive_timestamps_are_not_guessed():
    with pytest.raises(ValueError):
        business_iso("2026-11-09T08:00:00")
    with pytest.raises(ValidationError):
        TypeAdapter(BusinessDateTime).validate_python("2026-11-09T08:00:00")


def test_json_timezone_does_not_modify_python_datetime():
    adapter = TypeAdapter(BusinessDateTime)
    original = datetime(2026, 11, 9, 8, tzinfo=timezone.utc)
    assert adapter.dump_python(original) is original
    assert adapter.dump_python(original, mode="json") == "2026-11-09T16:00:00+08:00"
    assert business_display(original) == "2026-11-09 16:00:00 UTC+8"


def test_api_converts_existing_rows_without_rewriting_storage(client, db_engine):
    with db_engine.connect() as connection:
        before = connection.scalar(text("SELECT created_at FROM orders WHERE order_id='BF2026001'"))
    result = client.get('/api/v1/orders/BF2026001', headers={'X-Demo-User': 'employee-demo-001'})
    assert result.status_code == 200
    assert result.json()['created_at'] == '2026-10-01T16:00:00+08:00'
    with db_engine.connect() as connection:
        assert connection.scalar(text("SELECT created_at FROM orders WHERE order_id='BF2026001'")) == before
