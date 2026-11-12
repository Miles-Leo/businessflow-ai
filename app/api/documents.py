# 模块职责：知识文档管理入口；负责人显式导入，不在应用启动时更新知识库。
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from app.api.dependencies import DemoUser, require_reviewer
from app.services.knowledge_import import import_document, MAX_BYTES, DocumentInputError
from app.services.knowledge_import import active_documents

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


@router.get("/documents")
def list_documents(user: Annotated[DemoUser, Depends(require_reviewer)]):
    try:
        return active_documents()
    except Exception:
        raise HTTPException(503, "知识文档目录暂不可用") from None


@router.post("/documents", status_code=201)
def upload_document(user: Annotated[DemoUser, Depends(require_reviewer)], file: UploadFile = File(...)):
    try:
        return import_document(file.filename or "", file.file.read(MAX_BYTES + 1), user.user_id)
    except DocumentInputError as exc:
        raise HTTPException(422, str(exc)) from None
    except Exception:
        raise HTTPException(503, "文档导入未能确认，请查询文档目录确认生效版本，勿盲目重复提交") from None
    finally:
        file.file.close()
