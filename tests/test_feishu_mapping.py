from copy import deepcopy
from datetime import datetime, timezone

import pytest
from app.integrations.feishu import build_ticket_fields


@pytest.fixture
def ticket():
    return {
        "ticket_id": "TK-demo", "approval_id": "approval-demo", "order_id": "BF2026001",
        "issue_type": "shipping_delay", "description": "核查延迟原因", "status": "open",
        "created_at": "2026-11-08T08:00:00Z", "reviewer_id": "reviewer-demo-001",
    }


def test_mapping_matches_exact_columns_and_preserves_input(ticket):
    original = deepcopy(ticket)
    assert build_ticket_fields(ticket) == {
        "工单编号": "TK-demo", "审核编号": "approval-demo", "订单编号": "BF2026001",
        "问题类型": "shipping_delay", "工单描述": "核查延迟原因", "工单状态": "open",
        "创建时间": "2026-11-08T08:00:00Z",
    }
    assert ticket == original


@pytest.mark.parametrize("key", ["ticket_id", "approval_id", "order_id", "issue_type", "description", "status", "created_at"])
def test_missing_required_mapping_field_is_rejected(ticket, key):
    del ticket[key]
    with pytest.raises(ValueError, match=key):
        build_ticket_fields(ticket)


@pytest.mark.parametrize("value", [None, "", "  ", 123, datetime(2026, 11, 8, tzinfo=timezone.utc)])
def test_values_are_not_silently_stringified(ticket, value):
    ticket["created_at"] = value
    with pytest.raises(ValueError, match="created_at"):
        build_ticket_fields(ticket)
