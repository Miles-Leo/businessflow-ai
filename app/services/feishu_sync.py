# 模块职责：持久化同步意图后调用远端；未知结果只核对，不盲目重发。
from datetime import datetime, timezone
import re
from uuid import uuid4

from app.core.config import get_settings
from app.db.models import FeishuSync, Ticket, TicketExecution
from app.integrations.feishu import FeishuClient, FeishuError, FeishuWriteUnknown, build_ticket_fields
from app.integrations.feishu import feishu_text
from app.schemas.feishu_sync import FeishuSyncResponse
from app.schemas.ticket import TicketResponse


class SyncConflict(ValueError):
    pass


class SyncNotFound(SyncConflict):
    pass


def matched_record(records, fields):
    if len(records) > 1:
        raise FeishuWriteUnknown("存在重复远端记录，需人工核对")
    if records:
        row = records[0]
        if any(feishu_text(row["fields"].get(k)) != v for k, v in fields.items()):
            raise FeishuWriteUnknown("远端同编号记录内容不一致，需人工核对")
        return row["record_id"]
    return None


# 维护约束：先提交同步占位记录，再发起网络请求，避免跨网络持有数据库锁。
def sync_ticket(session_factory, ticket_id: str, requested_by: str, *, settings=None, client=None) -> FeishuSyncResponse:
    """Internal service: API must authenticate/authorize requested_by before calling.

    Claim is committed before I/O. Unknown/in-progress results are never retried
    automatically, including after process crash or local acknowledgement failure.
    """
    settings = settings if settings is not None else get_settings()
    target = (settings.feishu_bitable_app_token, settings.feishu_bitable_table_id)
    if not all(re.fullmatch(r"[A-Za-z0-9_-]+", value) for value in target):
        raise SyncConflict("同步目标未配置或无效")
    if not isinstance(requested_by, str) or not requested_by.strip():
        raise SyncConflict("同步操作人不能为空")
    with session_factory() as session, session.begin():
        if session.bind.dialect.name == "sqlite":
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        ticket = session.get(Ticket, ticket_id)
        if ticket is None:
            raise SyncNotFound("正式工单不存在")
        execution = session.get(TicketExecution, ticket.approval_id)
        if execution is None or execution.status != "success" or execution.ticket_id != ticket_id:
            raise SyncConflict("工单没有匹配的成功执行记录")
        fields = build_ticket_fields(TicketResponse.model_validate(ticket).model_dump(mode="json"))
        saved = session.get(FeishuSync, ticket_id)
        update_mode = False
        previous_fields = None
        if saved is not None:
            if (saved.app_token, saved.table_id) != target:
                raise SyncConflict("同步目标或内容已变化，不能复用旧请求标识")
            if saved.status in ("unknown", "in_progress"):
                raise SyncConflict("同步结果未知或正在处理，请核对远端记录，禁止直接重发")
            if saved.fields != fields:
                if not saved.record_id or any(saved.fields.get(k) != v for k, v in fields.items() if k != "工单状态"):
                    raise SyncConflict("同步目标或内容已变化，不能复用旧请求标识")
                previous_fields = dict(saved.fields)
                saved.fields = fields
                saved.request_id = str(uuid4())
                update_mode = True
            elif saved.status == "success":
                return FeishuSyncResponse.model_validate(saved)
            elif saved.record_id:
                update_mode = True
        else:
            saved = FeishuSync(ticket_id=ticket_id, request_id=str(uuid4()),
                               app_token=target[0], table_id=target[1], fields=fields,
                               attempts=0, status="in_progress")
            session.add(saved)
        saved.status = "in_progress"
        saved.error = None
        saved.attempts += 1
        saved.requested_by = requested_by.strip()
        saved.updated_at = datetime.now(timezone.utc)
        request_id = saved.request_id
        saved_record_id = saved.record_id
    # The request UUID, exact payload and target are now durable; no DB lock over network.
    record_id = saved_record_id if update_mode else None
    error = None
    try:
        api = client if client is not None else FeishuClient(settings)
        api.validate_ticket_fields(fields)
        records = api.find_records_by_ticket(ticket_id)
        if update_mode:
            if len(records) != 1 or records[0]["record_id"] != saved_record_id:
                raise FeishuWriteUnknown("原同步记录未能唯一匹配")
            actual = records[0]["fields"]
            if any(feishu_text(actual.get(k)) != v for k, v in fields.items() if k != "工单状态"):
                raise FeishuWriteUnknown("远端工单内容冲突")
            if feishu_text(actual.get("工单状态")) != fields["工单状态"]:
                if previous_fields and feishu_text(actual.get("工单状态")) != previous_fields["工单状态"]:
                    raise FeishuWriteUnknown("远端工单状态冲突")
                record_id = api.update_record_status(saved_record_id, fields["工单状态"])
        else:
            record_id = matched_record(records, fields)
            if record_id is None:
                record_id = api.create_record(fields, request_id)
        if not isinstance(record_id, str) or not record_id.strip():
            raise FeishuWriteUnknown("无有效记录 ID")
        status = "success"
    except FeishuWriteUnknown:
        status, error = "unknown", "远端写入结果未知，请核对记录，不要直接重试"
    except FeishuError:
        status, error = "failed", "飞书明确拒绝或请求准备失败，请检查权限和配置"
    except Exception:
        status, error = "unknown", "同步发生异常，远端结果未确认，请核对记录"
    with session_factory() as session, session.begin():
        saved = session.get(FeishuSync, ticket_id)
        saved.status, saved.record_id, saved.error = status, record_id, error
        saved.updated_at = datetime.now(timezone.utc)
        session.flush()
        result = FeishuSyncResponse.model_validate(saved)
    # If this commit fails, the durable in_progress claim blocks duplicate creation.
    return result


def get_sync(session_factory, ticket_id):
    with session_factory() as session:
        row = session.get(FeishuSync, ticket_id)
        if row is None:
            raise SyncNotFound("尚无同步记录")
        return FeishuSyncResponse.model_validate(row)


def reconcile_sync(session_factory, ticket_id, *, settings=None, client=None):
    """Read-only remote reconciliation; zero matches never authorizes a resend."""
    settings = settings if settings is not None else get_settings()
    with session_factory() as session:
        row = session.get(FeishuSync, ticket_id)
        if row is None:
            raise SyncNotFound("尚无同步记录")
        if (row.app_token, row.table_id) != (settings.feishu_bitable_app_token, settings.feishu_bitable_table_id):
            raise SyncConflict("核对目标与原同步目标不一致")
        if row.status == "success":
            return FeishuSyncResponse.model_validate(row)
        fields, request_id = dict(row.fields), row.request_id
    api = client if client is not None else FeishuClient(settings)
    record_id = matched_record(api.find_records_by_ticket(ticket_id), fields)
    if not record_id:
        raise SyncConflict("未找到匹配记录，仍不能确认写入结果；未解除重发限制")
    with session_factory() as session, session.begin():
        if session.bind.dialect.name == "sqlite":
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        row = session.get(FeishuSync, ticket_id)
        if row.request_id != request_id:
            raise SyncConflict("同步记录已变化，请重新核对")
        row.status, row.record_id, row.error = "success", record_id, None
        row.updated_at = datetime.now(timezone.utc)
        session.flush()
        return FeishuSyncResponse.model_validate(row)
