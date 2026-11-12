from copy import deepcopy
import json
import pytest
from unittest.mock import patch

from langchain_core.documents import Document
from pydantic import ValidationError
from app.ai.tools import search_policy, policy_search_tool


def test_policy_tool_validates_and_trims_question():
    document = Document(page_content="审核要求", metadata={
        "chunk_id": "policy:5", "document_title": "测试政策",
        "section": "AS-05", "source": "policy.md", "score": 0.8,
    })
    with patch("app.ai.tools.retrieve_policy", return_value=[document]) as retrieve:
        result = policy_search_tool.invoke({"question": "  审核要求？  "})
    retrieve.assert_called_once_with("审核要求？", top_k=5)
    assert result["status"] == "success"
    assert result["data"][0]["text"] == "审核要求"


@pytest.mark.parametrize("payload", [
    {}, {"question": ""}, {"question": " \t\n "},
    {"question": "a" * 2001}, {"question": None},
])
def test_policy_tool_invalid_input_skips_retrieval(payload):
    with patch("app.ai.tools.retrieve_policy") as retrieve:
        with pytest.raises(ValidationError):
            policy_search_tool.invoke(payload)
        retrieve.assert_not_called()


def test_search_policy_returns_serializable_passages():
    documents = [Document(page_content=f"规则{index}", metadata={
        "chunk_id": f"policy:{index}", "document_title": "测试政策",
        "section": f"AS-0{index}", "source": "policy.md", "score": 0.8,
    }) for index in (1, 2)]
    original = deepcopy(documents)
    with patch("app.ai.tools.retrieve_policy", return_value=documents) as retrieve:
        result = search_policy("工单审核条件？")
    retrieve.assert_called_once_with("工单审核条件？", top_k=5)
    assert result == {
        "status": "success",
        "data": [{"text": doc.page_content, **doc.metadata} for doc in documents],
        "error": None,
    }
    assert json.loads(json.dumps(result)) == result
    assert documents == original


def test_search_policy_no_hits():
    with patch("app.ai.tools.retrieve_policy", return_value=[]) as retrieve:
        result = search_policy("未知政策")
    retrieve.assert_called_once_with("未知政策", top_k=5)
    assert result["status"] == "not_found"
    assert result["data"] == []
    assert result["error"]


@pytest.mark.parametrize("failure", [RuntimeError("internal-secret"), ConnectionError("private-host")])
def test_search_policy_failure_is_not_reported_as_no_hits(failure):
    with patch("app.ai.tools.retrieve_policy", side_effect=failure):
        result = search_policy("审核要求？")
    assert result == {
        "status": "failed", "data": [],
        "error": "政策检索暂时不可用，请稍后重试",
    }
    assert "internal-secret" not in json.dumps(result)
    assert "private-host" not in json.dumps(result)


def test_malformed_passage_returns_failure_instead_of_partial_results():
    incomplete = Document(page_content="正文", metadata={})
    with patch("app.ai.tools.retrieve_policy", return_value=[incomplete]):
        result = search_policy("审核要求？")
    assert result["status"] == "failed"
    assert result["data"] == []
    assert "chunk_id" not in result["error"]
