from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


@pytest.mark.parametrize("top_k", [None, 2])
def test_policy_query_preserves_sources(top_k):
    result = {"answer": "需要审核[1]", "sources": [{
        "citation_id": 1, "chunk_id": "policy:5", "document_title": "测试政策",
        "section": "AS-05", "source": "policy.md", "score": 0.8,
    }]}
    answerer = Mock(return_value=result)
    payload = {"question": "  创建条件是什么？  "}
    if top_k is not None:
        payload["top_k"] = top_k
    with patch("app.api.knowledge.get_policy_answerer", return_value=answerer):
        response = client.post("/api/v1/knowledge/query", json=payload)
    assert response.status_code == 200
    assert response.json() == result
    answerer.assert_called_once_with("创建条件是什么？", top_k=5 if top_k is None else top_k)


@pytest.mark.parametrize("payload", [
    {}, {"question": ""}, {"question": "  "}, {"question": "a" * 2001},
    {"question": "问题", "top_k": 0}, {"question": "问题", "top_k": 11},
    {"question": "问题", "top_k": True}, {"question": "问题", "top_k": "3"},
])
def test_invalid_policy_query_skips_retrieval(payload):
    with patch("app.api.knowledge.get_policy_answerer") as factory:
        response = client.post("/api/v1/knowledge/query", json=payload)
    assert response.status_code == 422
    factory.assert_not_called()


def test_no_hits_returns_information_insufficient():
    result = {"answer": "信息不足", "sources": []}
    with patch("app.api.knowledge.get_policy_answerer", return_value=Mock(return_value=result)):
        response = client.post("/api/v1/knowledge/query", json={"question": "问题"})
    assert response.status_code == 200
    assert response.json() == result


def test_dependency_import_failure():
    with patch("app.api.knowledge.get_policy_answerer", side_effect=RuntimeError("secret")):
        response = client.post("/api/v1/knowledge/query", json={"question": "问题"})
    assert response.status_code == 503
    assert "secret" not in response.text


@pytest.mark.parametrize("result", [None, {"answer": "", "sources": []}, {"answer": "回答", "sources": [{}]}])
def test_invalid_result_returns_safe_error(result):
    with patch("app.api.knowledge.get_policy_answerer", return_value=Mock(return_value=result)):
        response = client.post("/api/v1/knowledge/query", json={"question": "问题"})
    assert response.status_code == 502


def test_retrieval_failure_returns_safe_error():
    with patch("app.api.knowledge.get_policy_answerer", return_value=Mock(side_effect=RuntimeError("secret"))):
        response = client.post("/api/v1/knowledge/query", json={"question": "问题"})
    assert response.status_code == 502
    assert "secret" not in response.text


def test_policy_endpoint_is_documented():
    assert "/api/v1/knowledge/query" in client.get("/openapi.json").json()["paths"]
