import sys
from types import ModuleType
from unittest.mock import Mock

import pytest

from app.ai.task_nodes import generate_proposal


@pytest.fixture
def prepare(monkeypatch):
    module = ModuleType("app.ai.review")
    module.prepare_ticket_proposal_result = Mock()
    monkeypatch.setitem(sys.modules, "app.ai.review", module)
    return module.prepare_ticket_proposal_result


def test_success_returns_proposal_without_mutating_state(prepare):
    proposal = {"order_id": "BF2026001", "approval_status": "pending"}
    prepare.return_value = (proposal, "订单查询结果：测试摘要", None)
    state = {"order_id": "BF2026001", "proposal": None, "error": "旧错误"}
    original = state.copy()

    assert generate_proposal(state) == {"proposal": proposal, "answer": "订单查询结果：测试摘要", "result": None, "error": None}
    prepare.assert_called_once_with("BF2026001", structured=True)
    assert state == original


@pytest.mark.parametrize("order_id", [None, ""])
def test_missing_order_does_not_prepare_and_clears_stale_proposal(prepare, order_id):
    result = generate_proposal({"order_id": order_id, "proposal": {"old": True}})
    assert result == {"proposal": None, "error": "生成待审核建议需要提供订单编号"}
    prepare.assert_not_called()


@pytest.mark.parametrize("failure,expected", [
    (ValueError("sensitive details"), "未能满足建议生成条件，请检查订单评估和政策依据"),
    (RuntimeError("sensitive details"), "建议生成暂时不可用，请稍后重试"),
])
def test_failure_clears_proposal_and_hides_internal_details(prepare, failure, expected):
    prepare.side_effect = failure
    assert generate_proposal({"order_id": "BF2026001", "proposal": {"old": True}}) == {
        "proposal": None, "error": expected,
    }


def test_import_failure_is_safe(monkeypatch):
    monkeypatch.setitem(sys.modules, "app.ai.review", None)
    assert generate_proposal({"order_id": "BF2026001"}) == {
        "proposal": None, "error": "建议生成暂时不可用，请稍后重试",
    }
