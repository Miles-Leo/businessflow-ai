from unittest.mock import patch
import pytest
from app.ai.review import prepare_ticket_proposal_result
from app.ai.fixed_evaluation import order_fixture, policy_rows, load_cases
from app.services.task_answers import with_progress


def test_query_and_proposal_use_same_single_order_lookup():
    order = order_fixture('overdue', 'BF2026001', load_cases()['checked_at'])
    policy = {'status': 'success', 'data': policy_rows(['AS-04', 'AS-05'])}
    with patch('app.ai.review.lookup_order', return_value=order) as lookup, patch('app.ai.review.search_policy', return_value=policy):
        proposal, answer = prepare_ticket_proposal_result('BF2026001')
    lookup.assert_called_once_with('BF2026001')
    assert proposal['approval_status'] == 'pending'
    for expected in ['BF2026001', 'pending', '尚未发货', '超期未发货判定：是', '2026-10-02 16:00:00 UTC+8', 'AS-04', 'AS-05', 'knowledge/after_sales_policy.md']:
        assert expected in answer


@pytest.mark.parametrize('kind', ['not_due', 'on_time', 'late_shipped'])
def test_condition_not_met_returns_query_result_without_proposal_or_policy_search(kind):
    order = order_fixture(kind, 'BF2026001', load_cases()['checked_at'])
    with patch('app.ai.review.lookup_order', return_value=order), patch('app.ai.review.search_policy') as search:
        proposal, answer = prepare_ticket_proposal_result('BF2026001')
    assert proposal is None
    assert '超期未发货判定：否' in answer
    assert '本次未生成待审核建议' in answer
    search.assert_not_called()


def test_failed_query_does_not_fabricate_summary():
    with patch('app.ai.review.lookup_order', return_value={'status':'failed'}), patch('app.ai.review.search_policy') as search:
        with pytest.raises(ValueError):
            prepare_ticket_proposal_result('BF2026001')
    search.assert_not_called()


def test_refresh_replaces_outcome_but_retains_original_facts():
    first = with_progress('订单查询结果\n订单状态：pending', '等待负责人审核')
    updated = with_progress(first, '正式工单已创建，编号：TK-demo')
    assert '订单状态：pending' in updated
    assert '等待负责人审核' not in updated
    assert updated.count('处理进度：') == 1
    assert with_progress('旧任务已提交', '审核已拒绝') == '审核已拒绝'
