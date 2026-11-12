from app.core.time import business_display
from copy import deepcopy
from unittest.mock import patch

import pytest
from app.ai.review import build_ticket_proposal, prepare_ticket_proposal


def test_prepare_proposal_passes_tool_results_to_builder():
    order_result = {"status": "success"}
    policy_result = {"status": "success", "data": []}
    expected = {"approval_status": "pending"}
    with patch("app.ai.review.lookup_order", return_value=order_result) as lookup, patch(
        "app.ai.review.search_policy", return_value=policy_result
    ) as search, patch("app.ai.review.build_ticket_proposal", return_value=expected) as build:
        result = prepare_ticket_proposal("BF2026099")
    lookup.assert_called_once_with("BF2026099")
    search.assert_called_once_with("超期未发货时提出发货延迟核查建议的条件，以及负责人审核和正式创建工单的限制是什么？")
    build.assert_called_once_with(order_result, policy_result)
    assert result is expected


def test_prepare_proposal_uses_real_builder_checks(proposal_inputs):
    order, policy = proposal_inputs
    with patch("app.ai.review.lookup_order", return_value=order), patch(
        "app.ai.review.search_policy", return_value=policy
    ):
        result = prepare_ticket_proposal("BF2026001")
    assert result["order_id"] == "BF2026001"
    assert result["approval_status"] == "pending"
    assert result["checked_at"] == order["assessment"]["checked_at"]


def test_prepare_does_not_bypass_missing_policy_checks(proposal_inputs):
    order, policy = proposal_inputs
    policy["data"] = []
    with patch("app.ai.review.lookup_order", return_value=order), patch(
        "app.ai.review.search_policy", return_value=policy
    ):
        with pytest.raises(ValueError, match="为空"):
            prepare_ticket_proposal("BF2026001")


@pytest.fixture
def proposal_inputs():
    order = {
        "status": "success",
        "data": {"order_id": "BF2026001", "promised_ship_at": "2026-10-02T08:00:00Z"},
        "assessment": {"order_id": "BF2026001", "checked_at": "2026-11-07T08:00:00+00:00", "is_overdue_unshipped": True},
    }
    policy = {"status": "success", "data": [
        {"document_title": "测试政策", "section": code + "：条款", "source": "policy.md",
         "chunk_id": code, "text": "测试正文"}
        for code in ("AS-02", "AS-04", "AS-05")
    ]}
    return order, policy


def test_proposal_is_pending_and_preserves_evidence(proposal_inputs):
    order, policy = proposal_inputs
    original = deepcopy(proposal_inputs)
    proposal = build_ticket_proposal(order, policy)
    assert set(proposal) == {"order_id", "issue_type", "description", "policy_sources", "checked_at", "approval_status"}
    assert proposal["order_id"] == "BF2026001"
    assert proposal["issue_type"] == "shipping_delay"
    assert proposal["approval_status"] == "pending"
    assert proposal["checked_at"] == order["assessment"]["checked_at"]
    assert business_display(order["data"]["promised_ship_at"]) in proposal["description"]
    assert business_display(proposal["checked_at"]) in proposal["description"]
    assert "已创建" not in proposal["description"]
    assert proposal["policy_sources"] == [
        {key: passage[key] for key in ("document_title", "section", "source", "chunk_id")}
        for passage in policy["data"][1:]
    ]
    assert proposal_inputs == original


@pytest.mark.parametrize("status", ["not_found", "failed"])
def test_unsuccessful_order_is_rejected(proposal_inputs, status):
    order, policy = proposal_inputs
    order["status"] = status
    with pytest.raises(ValueError, match="订单查询"):
        build_ticket_proposal(order, policy)


@pytest.mark.parametrize("value", [False, None, 1, "true"])
def test_only_explicit_true_assessment_is_accepted(proposal_inputs, value):
    order, policy = proposal_inputs
    order["assessment"]["is_overdue_unshipped"] = value
    with pytest.raises(ValueError, match="不属于超期未发货"):
        build_ticket_proposal(order, policy)


@pytest.mark.parametrize("status", ["not_found", "failed"])
def test_unsuccessful_policy_search_is_rejected(proposal_inputs, status):
    order, policy = proposal_inputs
    policy["status"] = status
    with pytest.raises(ValueError, match="政策查询失败"):
        build_ticket_proposal(order, policy)


def test_empty_policy_is_rejected(proposal_inputs):
    order, policy = proposal_inputs
    policy["data"] = []
    with pytest.raises(ValueError, match="为空"):
        build_ticket_proposal(order, policy)


@pytest.mark.parametrize("missing", ["AS-04", "AS-05"])
def test_missing_required_clause_is_rejected(proposal_inputs, missing):
    order, policy = proposal_inputs
    policy["data"] = [p for p in policy["data"] if not p["section"].startswith(missing)]
    with pytest.raises(ValueError, match="缺少处理建议或审核边界"):
        build_ticket_proposal(order, policy)
