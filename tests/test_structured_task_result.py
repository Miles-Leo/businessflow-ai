from unittest.mock import Mock, patch
from app.ai.fixed_evaluation import order_fixture, policy_rows, load_cases
from app.ai.review import prepare_ticket_proposal_result

HEADERS = {'X-Demo-User': 'employee-demo-001'}


def test_result_persists_separately_from_answer(client):
    order = order_fixture('not_due', 'BF2026001', load_cases()['checked_at'])
    with patch('app.ai.review.lookup_order', return_value=order):
        proposal, answer, result = prepare_ticket_proposal_result('BF2026001', structured=True)
    assert proposal is None
    task_id = client.post('/api/v1/agent/tasks', headers=HEADERS, json={'user_input':'查询订单并条件生成建议'}).json()['task_id']
    graph = Mock()
    graph.invoke.return_value = {'answer':answer, 'result':result, 'error':None}
    with patch('app.services.tasks.get_task_graph', return_value=graph):
        response = client.post(f'/api/v1/agent/tasks/{task_id}/run', headers=HEADERS)
    assert response.status_code == 200
    saved = client.get(f'/api/v1/agent/tasks/{task_id}', headers=HEADERS).json()
    assert saved['status'] == 'completed'
    assert saved['result']['query_result']['order_id'] == 'BF2026001'
    assert saved['result']['assessment']['is_overdue_unshipped'] is False
    assert saved['result']['proposal'] is None
    assert saved['result']['query_result']['created_at'].endswith('+08:00')


def test_policy_failure_retains_query_evidence():
    order = order_fixture('overdue', 'BF2026001', load_cases()['checked_at'])
    with patch('app.ai.review.lookup_order', return_value=order), patch('app.ai.review.search_policy', return_value={'status':'failed','data':[]}):
        proposal, answer, result = prepare_ticket_proposal_result('BF2026001', structured=True)
    assert proposal is None and result['issue']
    assert result['query_result'] == order['data']
    assert result['assessment'] == order['assessment']
    assert '服务暂不可用' in result['issue']


def test_structured_proposal_contains_exact_facts_and_sources():
    order = order_fixture('overdue', 'BF2026001', load_cases()['checked_at'])
    policy = {'status':'success','data':policy_rows(['AS-04','AS-05'])}
    with patch('app.ai.review.lookup_order',return_value=order), patch('app.ai.review.search_policy',return_value=policy):
        proposal, _, result = prepare_ticket_proposal_result('BF2026001',structured=True)
    assert result['query_result'] == order['data']
    assert result['proposal'] == proposal
    assert len(result['policy_sources']) == 2
