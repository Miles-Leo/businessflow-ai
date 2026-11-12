from copy import deepcopy
from unittest.mock import patch

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.ai.rag import answer_policy_question, format_policy_context
from app.ai.prompts import POLICY_QA_SYSTEM_PROMPT


def test_no_documents_skips_model():
    with patch("app.ai.rag.retrieve_policy", return_value=[]) as retrieve, patch(
        "app.ai.rag.create_chat_model"
    ) as create:
        result = answer_policy_question("没有依据的问题")
    retrieve.assert_called_once_with("没有依据的问题", top_k=5)
    create.assert_not_called()
    assert result["sources"] == []
    assert "信息不足" in result["answer"]


def test_policy_answer_preserves_numbered_sources():
    documents = [Document(
        page_content=f"规则正文{index}",
        metadata={"chunk_id": f"policy:{index}", "source": "policy.md",
                  "document_title": "测试政策", "section": f"AS-0{index}", "score": 0.8},
    ) for index in (1, 2)]
    original = deepcopy(documents)
    with patch("app.ai.rag.retrieve_policy", return_value=documents) as retrieve, patch(
        "app.ai.rag.create_chat_model"
    ) as create:
        create.return_value.invoke.return_value = AIMessage(content="政策说明[1][2]")
        result = answer_policy_question("如何处理？", top_k=2)
    retrieve.assert_called_once_with("如何处理？", top_k=2)
    create.return_value.invoke.assert_called_once()
    messages = create.return_value.invoke.call_args.args[0]
    assert isinstance(messages[0], SystemMessage)
    assert messages[0].content == POLICY_QA_SYSTEM_PROMPT
    assert isinstance(messages[1], HumanMessage)
    assert "如何处理？" in messages[1].content
    assert format_policy_context(documents) in messages[1].content
    assert result["answer"] == "政策说明[1][2]"
    assert result["sources"] == [
        {"citation_id": index, **doc.metadata}
        for index, doc in enumerate(documents, start=1)
    ]
    assert documents == original


def test_empty_context():
    assert format_policy_context([]) == ""


def test_context_numbers_match_document_order():
    documents = [Document(page_content="正文", metadata={
        "document_title": "测试政策", "section": "AS-05", "source": "policy.md",
    })]
    context = format_policy_context(documents)
    assert context.startswith("[1]\n")
    assert "测试政策" in context
    assert "AS-05" in context
    assert "policy.md" in context
    assert "正文" in context
