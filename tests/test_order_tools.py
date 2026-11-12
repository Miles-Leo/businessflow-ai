from app.core.time import business_iso
import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.ai.tools import lookup_order, order_lookup_tool


@pytest.mark.parametrize("order_id,expected", [
    ("BF2026001", True), ("BF2026002", False), ("BF2026003", False),
])
def test_order_assessment_uses_server_utc_time(db_engine, order_id, expected):
    checked = datetime(2026, 11, 7, 8, tzinfo=timezone.utc)
    with patch("app.ai.tools.SessionLocal", sessionmaker(bind=db_engine)), patch(
        "app.ai.tools.datetime"
    ) as clock:
        clock.now.return_value = checked
        result = order_lookup_tool.invoke({"order_id": order_id})
    clock.now.assert_called_once_with(timezone.utc)
    assert result["status"] == "success"
    assert result["assessment"] == {
        "order_id": order_id, "checked_at": business_iso(checked),
        "is_overdue_unshipped": expected,
    }


def test_conflicting_order_returns_safe_assessment_failure(db_engine):
    from sqlalchemy.orm import Session
    from app.db.models import Order
    with Session(db_engine) as session, session.begin():
        session.get(Order, "BF2026001").status = "shipped"
    with patch("app.ai.tools.SessionLocal", sessionmaker(bind=db_engine)):
        result = lookup_order("BF2026001")
    assert result == {
        "status": "failed", "data": None, "assessment": None,
        "error": "订单数据不完整或存在冲突，暂时无法判断发货情况",
    }


def test_structured_tool_valid_input(db_engine):
    with patch("app.ai.tools.SessionLocal", sessionmaker(bind=db_engine)):
        result = order_lookup_tool.invoke({"order_id": "BF2026001"})
    assert result["status"] == "success"
    assert result["data"]["order_id"] == "BF2026001"


@pytest.mark.parametrize("payload", [
    {"order_id": "BF20260012"},
    {"order_id": "abc"},
    {},
])
def test_structured_tool_invalid_input_skips_database(payload):
    with patch("app.ai.tools.SessionLocal") as factory:
        with pytest.raises(ValidationError):
            order_lookup_tool.invoke(payload)
        factory.assert_not_called()


def test_lookup_order_success(db_engine):
    with patch("app.ai.tools.SessionLocal", sessionmaker(bind=db_engine)):
        result = lookup_order("BF2026001")

    assert result["status"] == "success"
    assert result["error"] is None
    assert result["data"] == {
        "order_id": "BF2026001",
        "customer_id": "CUST-DEMO-001",
        "created_at": "2026-10-01T16:00:00+08:00",
        "promised_ship_at": "2026-10-02T16:00:00+08:00",
        "shipped_at": None,
        "status": "pending",
    }
    # The entire tool result must be usable outside the database session.
    assert json.loads(json.dumps(result)) == result


def test_lookup_order_not_found(db_engine):
    with patch("app.ai.tools.SessionLocal", sessionmaker(bind=db_engine)):
        result = lookup_order("BF9999999")

    assert result == {
        "status": "not_found", "data": None, "error": "订单不存在",
    }


@pytest.mark.parametrize("stage", ["connect", "query"])
def test_lookup_order_database_failure(stage):
    failure = OperationalError("SELECT private_data", {}, RuntimeError("internal-secret"))
    with patch("app.ai.tools.SessionLocal") as factory, patch(
        "app.ai.tools.get_order"
    ) as repository:
        if stage == "connect":
            factory.return_value.__enter__.side_effect = failure
        else:
            repository.side_effect = failure
        result = lookup_order("BF2026001")

    assert result == {
        "status": "failed",
        "data": None,
        "error": "订单查询暂时不可用，请稍后重试",
    }
    if stage == "query":
        factory.return_value.__exit__.assert_called_once()
