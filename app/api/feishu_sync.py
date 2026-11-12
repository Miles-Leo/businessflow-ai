# 模块职责：飞书同步与只读核对入口；授权后才允许触发外部写入。
from threading import Lock
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from app.api.dependencies import DemoUser, require_reviewer
from app.db.session import SessionLocal
from app.integrations.feishu import FeishuError
from app.schemas.feishu_sync import FeishuSyncResponse
from app.services.feishu_sync import sync_ticket, get_sync, reconcile_sync, SyncConflict, SyncNotFound

router = APIRouter(prefix="/tickets", tags=["feishu-sync"])
_sync_lock = Lock()


def get_sync_session_factory():
    return SessionLocal


def translate_error(exc):
    if isinstance(exc, SyncNotFound):
        return HTTPException(404, str(exc))
    if isinstance(exc, SyncConflict):
        return HTTPException(409, str(exc))
    return HTTPException(503, "同步服务暂不可用，请先查询本地状态，勿盲目重试")


@router.get("/{ticket_id}/feishu-sync", response_model=FeishuSyncResponse)
def read_sync(ticket_id: str, user: Annotated[DemoUser, Depends(require_reviewer)], factory=Depends(get_sync_session_factory)):
    try:
        return get_sync(factory, ticket_id)
    except Exception as exc:
        raise translate_error(exc) from None


@router.post("/{ticket_id}/feishu-sync", response_model=FeishuSyncResponse)
def create_sync(ticket_id: str, user: Annotated[DemoUser, Depends(require_reviewer)], factory=Depends(get_sync_session_factory)):
    if not _sync_lock.acquire(blocking=False):
        raise HTTPException(409, "另一个同步操作正在处理")
    try:
        result = sync_ticket(factory, ticket_id, user.user_id)
        # An attempted write with a persisted failure is not an HTTP success.
        if result.status != "success":
            raise HTTPException(503, "同步未确认成功，请查看同步状态及安全错误说明")
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise translate_error(exc) from None
    finally:
        _sync_lock.release()


@router.post("/{ticket_id}/feishu-sync/reconcile", response_model=FeishuSyncResponse)
def reconcile(ticket_id: str, user: Annotated[DemoUser, Depends(require_reviewer)], factory=Depends(get_sync_session_factory)):
    if not _sync_lock.acquire(blocking=False):
        raise HTTPException(409, "另一个同步操作正在处理")
    try:
        return reconcile_sync(factory, ticket_id)
    except Exception as exc:
        raise translate_error(exc) from None
    finally:
        _sync_lock.release()
