from unittest.mock import Mock, patch

import pytest
from langchain_core.documents import Document

from app.ai.policy_relations import POLICY_SOURCE, POLICY_TITLE, complete_policy_context


def doc(section, source=POLICY_SOURCE, title=POLICY_TITLE):
    return Document(page_content=f"{section} 正文", metadata={"chunk_id": f"{source}:{section}",
        "source": source, "document_title": title, "section": section, "score": 0.8})


def row(document):
    return {**document.metadata, "text": document.page_content}


def test_missing_approval_clause_is_fetched_from_active_version():
    client = Mock()
    client.query.return_value = [row(doc("AS-05"))]
    documents = [doc("AS-06"), doc("AS-04"), doc("AS-02"), doc("AS-03"), doc("AS-01")]
    result = complete_policy_context(documents, client, [{"source": POLICY_SOURCE, "collection": "current-revision"}], "legacy", 5)
    assert len(result) == 5
    assert {"AS-02", "AS-04", "AS-05"} <= {d.metadata["section"] for d in result}
    args = client.query.call_args.kwargs
    assert args["collection_name"] == "current-revision"
    assert 'section like "AS-05%"' in args["filter"]
    assert result[1].metadata["retrieval_method"] == "related_clause"
    assert documents[0].metadata["section"] == "AS-06"


@pytest.mark.parametrize("budget", [1, 2, 3, 5])
def test_context_never_exceeds_budget_and_deduplicates(budget):
    client = Mock()
    client.query.return_value = [row(doc("AS-05")), row(doc("AS-05"))]
    result = complete_policy_context([doc("AS-04"), doc("AS-02")], client, [], "legacy", budget)
    assert len(result) <= budget
    assert len({d.metadata["chunk_id"] for d in result}) == len(result)
    if budget == 1:
        client.query.assert_not_called()
    if budget == 2:
        assert result[1].metadata["section"] == "AS-05"


@pytest.mark.parametrize("source,title", [("other.md", POLICY_TITLE), (POLICY_SOURCE, "另一个政策")])
def test_unrelated_documents_do_not_trigger_demo_relations(source, title):
    client = Mock()
    documents = [doc("AS-04", source, title)]
    assert complete_policy_context(documents, client, [], "legacy", 5) == documents
    client.query.assert_not_called()


def test_missing_clause_is_not_fabricated_and_wrong_document_rows_are_rejected():
    client = Mock()
    client.query.return_value = [row(doc("AS-05", "other.md")), row(doc("AS-05", title="wrong")), row(doc("AS-99"))]
    result = complete_policy_context([doc("AS-04")], client, [], "legacy", 5)
    assert [d.metadata["section"] for d in result] == ["AS-04"]


def test_already_retrieved_relations_require_no_second_read():
    client = Mock()
    complete_policy_context([doc("AS-04"), doc("AS-05"), doc("AS-02")], client, [], "legacy", 5)
    client.query.assert_not_called()


def test_windows_source_filter_is_literal_and_active_version_is_normalized():
    client = Mock()
    client.query.return_value = []
    source = POLICY_SOURCE.replace("/", "\\")
    complete_policy_context([doc("AS-04", source)], client, [{"source": POLICY_SOURCE, "collection": "v2"}], "legacy", 5)
    assert client.query.call_args.kwargs["collection_name"] == "v2"
    assert 'knowledge\\\\after_sales_policy.md' in client.query.call_args.kwargs["filter"]


def test_model_name_uses_settings_without_real_network():
    from app.ai.model import create_chat_model
    with patch("app.ai.model.get_settings") as settings, patch("app.ai.model.init_chat_model") as initialize:
        settings.return_value.dashscope_model = "configured-eval-model"
        create_chat_model()
    assert initialize.call_args.kwargs["model"] == "configured-eval-model"


def test_failed_related_read_is_not_treated_as_valid_policy_context():
    client = Mock()
    client.query.side_effect = RuntimeError("unavailable")
    with pytest.raises(RuntimeError, match="unavailable"):
        complete_policy_context([doc("AS-04")], client, [], "legacy", 5)


def test_evaluation_provenance_records_configured_model():
    from app.ai.fixed_evaluation import provenance
    from app.core.config import Settings
    settings = Settings(dashscope_model="configured-eval-model", _env_file=None)
    with patch("app.core.config.get_settings", return_value=settings):
        result = provenance()
    assert result["model"] == "configured-eval-model"
    assert "app/ai/policy_relations.py" in {key.replace("\\", "/") for key in result["code_sha256"]}
