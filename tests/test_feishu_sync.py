from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Event
from unittest.mock import Mock

import pytest
from sqlalchemy.orm import Session, sessionmaker
from app.core.config import Settings
from app.db.models import Ticket, TicketExecution, FeishuSync
from app.integrations.feishu import FeishuError, FeishuWriteUnknown
from app.services.feishu_sync import sync_ticket, reconcile_sync, get_sync, SyncConflict


@pytest.fixture
def sync_setup(db_engine):
    now = datetime(2026, 11, 8, tzinfo=timezone.utc)
    with Session(db_engine) as s, s.begin():
        s.add(Ticket(ticket_id="TK-demo", approval_id="a-demo", order_id="BF2026001",
            issue_type="shipping_delay", description="测试工单", status="open", created_at=now,
            reviewer_id="reviewer-demo-001", reviewed_at=now, executed_by="reviewer-demo-001", policy_sources=[]))
        s.add(TicketExecution(approval_id="a-demo", status="success", ticket_id="TK-demo", attempts=1, updated_at=now))
    return sessionmaker(bind=db_engine), Settings(_env_file=None, feishu_bitable_app_token="base-demo", feishu_bitable_table_id="tbl-demo")


def test_claim_is_durable_before_request_and_success_is_reused(sync_setup):
    factory, settings = sync_setup
    api = Mock()
    api.find_records_by_ticket.return_value = []
    def create(fields, request_id):
        with factory() as s:
            row = s.get(FeishuSync, "TK-demo")
            assert row.request_id == request_id
            assert row.fields == fields
            assert row.status == "in_progress"
        return "rec-demo"
    api.create_record.side_effect = create
    first = sync_ticket(factory, "TK-demo", "reviewer", settings=settings, client=api)
    second = sync_ticket(factory, "TK-demo", "reviewer", settings=settings, client=api)
    assert first.status == second.status == "success"
    assert second.record_id == "rec-demo"
    assert first.request_id == second.request_id
    assert second.attempts == 1
    api.create_record.assert_called_once()


def test_status_change_updates_existing_record_and_unknown_is_reconciled(sync_setup):
    factory, settings = sync_setup
    api = Mock()
    api.find_records_by_ticket.return_value = []
    api.create_record.return_value = "rec-demo"
    sync_ticket(factory, "TK-demo", "reviewer", settings=settings, client=api)
    with factory() as session, session.begin():
        old_fields = dict(session.get(FeishuSync, "TK-demo").fields)
        session.get(Ticket, "TK-demo").status = "closed"
    api.find_records_by_ticket.return_value = [{"record_id": "rec-demo", "fields": old_fields}]
    api.update_record_status.side_effect = FeishuWriteUnknown("private")
    unknown = sync_ticket(factory, "TK-demo", "reviewer", settings=settings, client=api)
    assert unknown.status == "unknown" and unknown.record_id == "rec-demo"
    with pytest.raises(SyncConflict):
        sync_ticket(factory, "TK-demo", "reviewer", settings=settings, client=api)
    api.find_records_by_ticket.return_value = [{"record_id": "rec-demo", "fields": {**old_fields, "工单状态": "closed"}}]
    fixed = reconcile_sync(factory, "TK-demo", settings=settings, client=api)
    assert fixed.status == "success" and fixed.record_id == "rec-demo"
    assert sync_ticket(factory, "TK-demo", "reviewer", settings=settings, client=api).attempts == 2
    api.create_record.assert_called_once()
    api.update_record_status.assert_called_once_with("rec-demo", "closed")


def test_definite_failure_retry_reuses_request(sync_setup):
    factory, settings = sync_setup
    api = Mock()
    api.find_records_by_ticket.return_value = []
    api.create_record.side_effect = [FeishuError("secret"), "rec-demo"]
    first = sync_ticket(factory, "TK-demo", "reviewer", settings=settings, client=api)
    second = sync_ticket(factory, "TK-demo", "reviewer", settings=settings, client=api)
    assert first.status == "failed"
    assert "secret" not in first.error
    assert second.status == "success" and second.attempts == 2
    assert first.request_id == second.request_id
    assert api.create_record.call_args_list[0] == api.create_record.call_args_list[1]


@pytest.mark.parametrize("failure", [FeishuWriteUnknown("secret"), RuntimeError("secret")])
def test_unknown_result_blocks_retry(sync_setup, failure):
    factory, settings = sync_setup
    api = Mock()
    api.find_records_by_ticket.return_value = []
    api.create_record.side_effect = failure
    result = sync_ticket(factory, "TK-demo", "reviewer", settings=settings, client=api)
    assert result.status == "unknown" and result.record_id is None
    assert "secret" not in result.error
    with pytest.raises(SyncConflict):
        sync_ticket(factory, "TK-demo", "reviewer", settings=settings, client=api)
    api.create_record.assert_called_once()


def test_changed_target_cannot_reuse_success(sync_setup):
    factory, settings = sync_setup
    api = Mock()
    api.find_records_by_ticket.return_value = []
    api.create_record.return_value = "rec-demo"
    sync_ticket(factory, "TK-demo", "reviewer", settings=settings, client=api)
    settings.feishu_bitable_table_id = "tbl-another"
    with pytest.raises(SyncConflict):
        sync_ticket(factory, "TK-demo", "reviewer", settings=settings, client=api)
    api.create_record.assert_called_once()


def test_without_successful_execution_skips_remote(sync_setup):
    factory, settings = sync_setup
    with factory() as s, s.begin():
        s.get(TicketExecution, "a-demo").status = "failed"
    api = Mock()
    api.find_records_by_ticket.return_value = []
    with pytest.raises(SyncConflict):
        sync_ticket(factory, "TK-demo", "reviewer", settings=settings, client=api)
    api.create_record.assert_not_called()


def test_concurrent_sync_only_one_remote_request(sync_setup):
    factory, settings = sync_setup
    started, release = Event(), Event()
    api = Mock()
    api.find_records_by_ticket.return_value = []
    def write(fields, request_id):
        started.set()
        assert release.wait(5)
        return "rec-demo"
    api.create_record.side_effect = write
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(sync_ticket, factory, "TK-demo", "reviewer", settings=settings, client=api)
        assert started.wait(5)
        try:
            with pytest.raises(SyncConflict):
                sync_ticket(factory, "TK-demo", "reviewer", settings=settings, client=api)
        finally:
            release.set()
        assert first.result().status == "success"
    api.create_record.assert_called_once()


def test_remote_existing_exact_record_is_adopted(sync_setup):
    factory, settings = sync_setup
    api = Mock()
    def find(ticket_id):
        with factory() as s:
            fields = s.get(FeishuSync, ticket_id).fields
        return [{"record_id": "rec-existing", "fields": fields}]
    api.find_records_by_ticket.side_effect = find
    result = sync_ticket(factory, "TK-demo", "reviewer", settings=settings, client=api)
    assert result.record_id == "rec-existing" and result.status == "success"
    api.create_record.assert_not_called()


def test_unknown_can_be_reconciled_without_writes(sync_setup):
    factory, settings = sync_setup
    api = Mock()
    api.find_records_by_ticket.return_value = []
    api.create_record.side_effect = FeishuWriteUnknown("timeout")
    sync_ticket(factory, "TK-demo", "reviewer", settings=settings, client=api)
    with factory() as s:
        fields = s.get(FeishuSync, "TK-demo").fields
    api.find_records_by_ticket.return_value = [{"record_id": "rec-found", "fields": fields}]
    result = reconcile_sync(factory, "TK-demo", settings=settings, client=api)
    assert result.status == "success" and result.record_id == "rec-found"
    assert get_sync(factory, "TK-demo").record_id == "rec-found"
    api.create_record.assert_called_once()


def test_unknown_zero_matches_does_not_authorize_retry(sync_setup):
    factory, settings = sync_setup
    api = Mock()
    api.find_records_by_ticket.return_value = []
    api.create_record.side_effect = FeishuWriteUnknown("timeout")
    sync_ticket(factory, "TK-demo", "reviewer", settings=settings, client=api)
    with pytest.raises(SyncConflict):
        reconcile_sync(factory, "TK-demo", settings=settings, client=api)
    assert get_sync(factory, "TK-demo").status == "unknown"
    api.create_record.assert_called_once()


def test_duplicate_remote_records_block_write(sync_setup):
    factory, settings = sync_setup
    api = Mock()
    api.find_records_by_ticket.return_value = [{}, {}]
    result = sync_ticket(factory, "TK-demo", "reviewer", settings=settings, client=api)
    assert result.status == "unknown"
    api.create_record.assert_not_called()
