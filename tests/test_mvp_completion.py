import asyncio
from datetime import datetime, timezone
from io import BytesIO
from unittest.mock import Mock, AsyncMock, patch

import pytest
from pypdf import PdfWriter
from sqlalchemy import select, func
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Customer, Order, AgentTask, KnowledgeDocument, TaskEvent, Ticket, TicketExecution, FeishuSync
from app.services.knowledge_import import parse_document, import_document, active_documents
from app.ai.evaluation import evaluate_rules, save_report

EMPLOYEE = {"X-Demo-User": "employee-demo-001"}
MANAGER = {"X-Demo-User": "reviewer-demo-001"}


def test_customer_scope_and_order_identity(client, db_engine):
    assert client.get("/api/v1/orders/BF2026001").status_code == 401
    assert client.get("/api/v1/customers/CUST-DEMO-001", headers=EMPLOYEE).json()["customer_id"] == "CUST-DEMO-001"
    with Session(db_engine) as session, session.begin():
        session.add(Customer(customer_id="PRIVATE", name="private", contact="private@example.invalid"))
        session.flush()
        session.add(Order(order_id="BF1111111", customer_id="PRIVATE", status="pending",
                          created_at=datetime.now(timezone.utc), promised_ship_at=datetime.now(timezone.utc), shipped_at=None))
    assert client.get("/api/v1/customers/PRIVATE", headers=EMPLOYEE).status_code == 404
    assert client.get("/api/v1/orders/BF1111111", headers=EMPLOYEE).status_code == 404
    assert client.get("/api/v1/customers/PRIVATE", headers=MANAGER).status_code == 200
    assert client.get("/api/v1/orders/BF1111111", headers=MANAGER).status_code == 200


def test_markdown_import_version_switch_and_failed_reimport(db_engine):
    factory = sessionmaker(bind=db_engine)
    api, embedding = Mock(), Mock()
    embedding.embed_documents.side_effect = lambda texts: [[0.1] * 1024 for _ in texts]
    first = import_document("policy.md", b"# Demo\n## AS-04\nOld policy", "reviewer", session_factory=factory, client=api, embeddings=embedding)
    old_collection = active_documents(factory)[0]["collection"]
    same = import_document("policy.md", b"# Demo\n## AS-04\nOld policy", "reviewer", session_factory=factory, client=api, embeddings=embedding)
    assert same["reused"] and same["document_id"] == first["document_id"]
    assert api.insert.call_count == 1
    import_document("policy.md", b"# Demo\nNew shorter policy", "reviewer", session_factory=factory, client=api, embeddings=embedding)
    new_collection = active_documents(factory)[0]["collection"]
    assert old_collection != new_collection and len(active_documents(factory)) == 1
    api.insert.side_effect = RuntimeError("private")
    with pytest.raises(RuntimeError):
        import_document("policy.md", b"# Third revision\nChanged body", "reviewer", session_factory=factory, client=api, embeddings=embedding)
    assert active_documents(factory)[0]["collection"] == new_collection
    api.delete.assert_not_called()
    api.drop_collection.assert_not_called()


@pytest.mark.parametrize("filename,content", [("../private.md", b"text"), ("x.exe", b"text"), ("x.md", b""), ("x.md", b"\xff")])
def test_import_rejects_invalid_input(filename, content):
    with pytest.raises(ValueError):
        parse_document(filename, content)


def test_pdf_import_extracts_text_and_rejects_empty_scan():
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 10 100 Td (Demo shipping policy) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    buffer = BytesIO()
    writer.write(buffer)
    chunks = parse_document("demo.pdf", buffer.getvalue())
    assert "shipping policy" in chunks[0].page_content
    assert chunks[0].metadata["section"] == "第1页"
    blank = PdfWriter()
    blank.add_blank_page(width=300, height=300)
    buffer = BytesIO()
    blank.write(buffer)
    with pytest.raises(ValueError, match="OCR"):
        parse_document("scan.pdf", buffer.getvalue())


def test_import_api_permissions_and_safe_failure(client):
    path = "/api/v1/knowledge/documents"
    assert client.post(path, headers=EMPLOYEE, files={"file": ("x.md", b"# demo")}).status_code == 403
    assert client.post(path, headers=MANAGER, files={"file": ("x.txt", b"demo")}).status_code == 422
    with patch("app.api.documents.import_document", side_effect=RuntimeError("secret")):
        response = client.post(path, headers=MANAGER, files={"file": ("x.md", b"# demo")})
    assert response.status_code == 503 and "secret" not in response.text


def test_mcp_is_actual_agent_order_tool():
    from importlib import import_module
    with patch("app.ai.model.create_chat_model"):
        agent = import_module("app.ai.agent")
    data = {"status": "success", "data": {"order_id": "BF2026001"}, "assessment": {"checked_at": "demo"}}
    with patch.object(agent, "query_order_via_mcp", new=AsyncMock(return_value=data)) as adapter:
        assert agent.lookup_order_using_mcp("BF2026001") == data
        adapter.assert_awaited_once_with("BF2026001")


def test_trace_is_payload_free_and_context_is_reset():
    from app.services.trace import capture_trace, record_step
    record_step("lookup_order")
    with capture_trace() as events:
        record_step("lookup_order", tool=True)
        record_step("private-token", tool=True)
    assert events == [("lookup_order", False, True)]
    record_step("search_policy")
    assert len(events) == 1


def test_recovery_no_checkpoint_and_active_execution(client, db_engine):
    from app.ai.recovery import task_execution_guard
    task = client.post("/api/v1/agent/tasks", headers=EMPLOYEE, json={"user_input": "query"}).json()
    task_id = task["task_id"]
    with Session(db_engine) as session, session.begin():
        session.get(AgentTask, task_id).status = "running"
    path = f"/api/v1/agent/tasks/{task_id}/recover"
    with task_execution_guard(task_id):
        assert client.post(path, headers=EMPLOYEE).status_code == 409
    with patch("app.services.tasks.refresh_task", return_value=type("Result", (), {"status": "running", "approval_id": None})()):
        response = client.post(path, headers=EMPLOYEE)
    assert response.status_code == 200 and response.json()["status"] == "failed"
    assert client.post(path, headers=MANAGER).status_code == 404


def test_deterministic_evaluation_and_saved_report(tmp_path):
    import json
    report = evaluate_rules()
    assert report["current_passed"] == report["total"] == 7
    assert report["baseline_passed"] < report["current_passed"]
    path = save_report(report, tmp_path)
    assert json.loads(path.read_text(encoding="utf-8")) == report


def test_hybrid_keyword_candidate_and_source_preservation():
    from langchain_core.documents import Document
    from app.ai.ranking import hybrid_rank
    def document(key, text):
        return Document(page_content=text, metadata={"chunk_id": key, "source": "policy.md", "score": 0.7})
    irrelevant = document("one", "物流签收说明")
    relevant = document("two", "负责人拒绝时禁止创建正式工单，必须审核批准")
    result = hybrid_rank("拒绝 审核 工单", [irrelevant], [irrelevant, relevant], 2)
    assert relevant in result and result[0].metadata["source"] == "policy.md"
    assert len({doc.metadata["chunk_id"] for doc in result}) == len(result)


def test_ticket_status_transition_and_permission(client, db_engine):
    now = datetime.now(timezone.utc)
    with Session(db_engine) as session, session.begin():
        session.add(Ticket(ticket_id="TK-status", approval_id="approval-status", order_id="BF2026001", issue_type="shipping_delay",
                           description="Demo", status="open", created_at=now, reviewer_id="reviewer-demo-001",
                           reviewed_at=now, executed_by="reviewer-demo-001", policy_sources=[]))
    url = "/api/v1/tickets/TK-status/status"
    assert client.patch(url, headers=EMPLOYEE, json={"status": "closed"}).status_code == 403
    assert client.patch(url, headers=MANAGER, json={"status": "closed"}).json()["status"] == "closed"
    assert client.patch(url, headers=MANAGER, json={"status": "closed"}).status_code == 200
    assert client.patch(url, headers=MANAGER, json={"status": "open"}).status_code == 409
    history = client.get("/api/v1/tickets/TK-status/status-history", headers=MANAGER).json()
    assert len(history) == 1 and history[0]["changed_by"] == "reviewer-demo-001"


def test_feishu_update_adapter_uses_existing_id_and_status_only():
    from app.integrations.feishu import FeishuClient
    from app.core.config import Settings
    api = FeishuClient(Settings(_env_file=None, feishu_bitable_app_token="base", feishu_bitable_table_id="table"))
    with patch.object(api, "get_tenant_access_token", return_value="demo-token"), patch("app.integrations.feishu.httpx.Client") as client:
        response = client.return_value.__enter__.return_value.put.return_value
        response.status_code = 200
        response.json.return_value = {"code": 0, "data": {"record": {"record_id": "rec-demo"}}}
        assert api.update_record_status("rec-demo", "closed") == "rec-demo"
        call = client.return_value.__enter__.return_value.put.call_args
        assert call.args[0].endswith("/records/rec-demo")
        assert call.kwargs["json"] == {"fields": {"工单状态": "closed"}}


def test_registry_retrieval_excludes_previous_source():
    from langchain_core.documents import Document
    from app.ai.rag import retrieve_policy
    api = Mock()
    api.has_collection.return_value = True
    old = {"chunk_id": "old", "distance": 0.9, "entity": {"source": "knowledge\\policy.md", "document_title": "Policy", "section": "old", "text": "OLD"}}
    new = {"chunk_id": "new", "distance": 0.8, "entity": {"source": "knowledge/policy.md", "document_title": "Policy", "section": "new", "text": "NEW"}}
    api.search.side_effect = [[[old]], [[new]]]
    with patch("app.ai.rag.MilvusClient", return_value=api), \
         patch("app.ai.rag.create_embeddings") as embeddings, \
         patch("app.services.knowledge_import.active_documents", return_value=[{"source": "knowledge/policy.md", "collection": "revision-new"}]):
        embeddings.return_value.embed_query.return_value = [0.1] * 1024
        result = retrieve_policy("policy")
    assert [doc.page_content for doc in result] == ["NEW"]
    api.close.assert_called_once()


def test_natural_language_sync_requires_manager_and_ticket_id():
    from app.ai.task_nodes import sync_formal_ticket
    from types import SimpleNamespace
    with patch("app.services.feishu_sync.sync_ticket") as sync:
        assert sync_formal_ticket({"user_id": "employee-demo-001", "ticket_id": "TK-demo"})["error"]
        assert sync_formal_ticket({"user_id": "reviewer-demo-001", "ticket_id": None})["error"]
        sync.assert_not_called()
        sync.return_value = SimpleNamespace(status="success", record_id="rec-demo")
        result = sync_formal_ticket({"user_id": "reviewer-demo-001", "ticket_id": "TK-demo"})
        assert result["ticket_id"] == "TK-demo" and result["error"] is None
        sync.return_value = SimpleNamespace(status="unknown", record_id=None)
        assert sync_formal_ticket({"user_id": "reviewer-demo-001", "ticket_id": "TK-demo"})["error"]
