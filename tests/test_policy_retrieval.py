from unittest.mock import Mock, patch

import pytest
from langchain_core.documents import Document
from app.ai.rag import retrieve_policy


def test_retrieval_preserves_content_and_citations():
    entity = {"text": "超期未发货可提出核查建议。", "source": "policy.md",
              "document_title": "测试政策", "section": "AS-04"}
    with patch("app.ai.rag.MilvusClient") as factory, patch(
        "app.ai.rag.create_embeddings"
    ) as embeddings:
        embeddings.return_value.embed_query.return_value = [0.1] * 1024
        factory.return_value.search.return_value = [[{
            "chunk_id": "policy:4", "distance": 0.7, "entity": entity,
        }]]
        documents = retrieve_policy("超期怎么办？", top_k=2)
        embeddings.return_value.embed_query.assert_called_once_with("超期怎么办？")
        arguments = factory.return_value.search.call_args.kwargs
        assert arguments["limit"] == 2
        assert arguments["data"] == [[0.1] * 1024]
        factory.return_value.close.assert_called_once()
    assert len(documents) == 1
    assert isinstance(documents[0], Document)
    assert documents[0].page_content == entity["text"]
    assert documents[0].metadata == {
        "source": "policy.md", "document_title": "测试政策", "section": "AS-04",
        "chunk_id": "policy:4", "score": 0.7,
    }


def test_retrieval_no_hits():
    with patch("app.ai.rag.MilvusClient") as factory, patch("app.ai.rag.create_embeddings"):
        factory.return_value.search.return_value = [[]]
        assert retrieve_policy("未命中") == []
        factory.return_value.close.assert_called_once()


@pytest.mark.parametrize("stage", ["embedding", "search"])
def test_retrieval_failure_closes_connection(stage):
    with patch("app.ai.rag.MilvusClient") as factory, patch(
        "app.ai.rag.create_embeddings"
    ) as embeddings:
        if stage == "embedding":
            embeddings.return_value.embed_query.side_effect = RuntimeError("test failure")
        else:
            factory.return_value.search.side_effect = RuntimeError("test failure")
        with pytest.raises(RuntimeError, match="test failure"):
            retrieve_policy("测试问题")
        factory.return_value.close.assert_called_once()
