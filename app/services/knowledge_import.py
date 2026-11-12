# 模块职责：知识版本导入；向量准备成功后切换生效指针，保留旧版本。
"""Versioned imports: publish the new collection only after vectors are durable.

Old collections are retained as inactive versions, never deleted automatically.
"""
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
from pathlib import PurePath
from threading import Lock
from uuid import uuid4

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader
from pymilvus import MilvusClient, DataType
from sqlalchemy import inspect, select

from app.core.config import get_settings
from app.db.models import KnowledgeDocument
from app.db.session import SessionLocal

import_lock = Lock()
MAX_BYTES = 5 * 1024 * 1024


class DocumentInputError(ValueError):
    """A safe, user-facing validation message, distinct from provider errors."""


def parse_document(filename: str, content: bytes) -> list[Document]:
    if not filename or "/" in filename or "\\" in filename or len(filename) > 200:
        raise DocumentInputError("文档名无效")
    if not content or len(content) > MAX_BYTES:
        raise DocumentInputError("文档不能为空且不能超过5MB")
    suffix = PurePath(filename).suffix.lower()
    source = f"knowledge/{filename}"
    if suffix == ".md":
        from app.ai.rag import split_markdown
        try:
            text = content.decode("utf-8-sig")
        except UnicodeError:
            raise DocumentInputError("Markdown 必须是 UTF-8 编码") from None
        docs = split_markdown(Document(page_content=text, metadata={"source": source}))
    elif suffix == ".pdf":
        try:
            reader = PdfReader(BytesIO(content))
            if reader.is_encrypted or len(reader.pages) > 100:
                raise DocumentInputError("PDF 不能加密且不能超过100页")
            docs = [Document(page_content=page.extract_text() or "", metadata={
                "source": source, "document_title": PurePath(filename).stem,
                "section": f"第{index + 1}页",
            }) for index, page in enumerate(reader.pages)]
        except DocumentInputError:
            raise
        except Exception:
            raise DocumentInputError("PDF 无法解析，请提供可提取文本的 PDF") from None
    else:
        raise DocumentInputError("仅支持 .md 和 .pdf")
    splitter = RecursiveCharacterTextSplitter(chunk_size=1200, chunk_overlap=150)
    chunks = splitter.split_documents([doc for doc in docs if doc.page_content.strip()])
    if not chunks:
        raise DocumentInputError("未提取到文本，扫描 PDF 需先完成 OCR")
    if len(chunks) > 500:
        raise DocumentInputError("文档超过500个片段，请拆分后导入")
    for chunk in chunks:
        chunk.metadata.setdefault("document_title", PurePath(filename).stem)
        chunk.metadata.setdefault("section", "正文")
    return chunks


def active_documents(session_factory=SessionLocal):
    with session_factory() as session:
        if not inspect(session.bind).has_table("knowledge_documents"):
            return []  # Backward-compatible retrieval before explicit upgrade.
        return [{"source": row.source, "collection": row.collection_name} for row in
                session.scalars(select(KnowledgeDocument)).all()]


def import_document(filename, content, imported_by, *, session_factory=SessionLocal, client=None, embeddings=None):
    chunks = parse_document(filename, content)
    source = chunks[0].metadata["source"]
    document_id, content_hash = sha256(source.encode()).hexdigest(), sha256(content).hexdigest()
    if not import_lock.acquire(blocking=False):
        raise RuntimeError("另一个导入正在处理")
    api = None
    try:
        with session_factory() as session:
            old = session.get(KnowledgeDocument, document_id)
            if old and old.content_hash == content_hash:
                return {"document_id": document_id, "source": source, "chunk_count": old.chunk_count, "reused": True}
        from app.ai.embedding import create_embeddings
        vectorizer = embeddings if embeddings is not None else create_embeddings()
        vectors = vectorizer.embed_documents([chunk.page_content for chunk in chunks])
        if len(vectors) != len(chunks) or any(len(vector) != 1024 for vector in vectors):
            raise ValueError("Embedding 维度或数量不符")
        api = client if client is not None else MilvusClient(uri=get_settings().milvus_uri)
        collection = "bf_document_" + uuid4().hex
        schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False)
        for field, length in (("chunk_id", 1024), ("text", 65535), ("source", 1024), ("document_title", 1024), ("section", 1024)):
            schema.add_field(field_name=field, datatype=DataType.VARCHAR, max_length=length, is_primary=field == "chunk_id")
        schema.add_field(field_name="embedding", datatype=DataType.FLOAT_VECTOR, dim=1024)
        indexes = api.prepare_index_params()
        indexes.add_index(field_name="embedding", index_type="AUTOINDEX", metric_type="COSINE")
        api.create_collection(collection_name=collection, schema=schema, index_params=indexes)
        records = [{"chunk_id": f"{document_id}:{i}", "text": chunk.page_content,
                    "source": source, "document_title": chunk.metadata["document_title"],
                    "section": chunk.metadata["section"], "embedding": vector}
                   for i, (chunk, vector) in enumerate(zip(chunks, vectors))]
        api.insert(collection_name=collection, data=records)
        api.flush(collection_name=collection)
        api.load_collection(collection_name=collection)
        with session_factory() as session, session.begin():
            row = session.get(KnowledgeDocument, document_id)
            if row is None:
                row = KnowledgeDocument(document_id=document_id, source=source)
                session.add(row)
            row.content_hash, row.collection_name = content_hash, collection
            row.chunk_count, row.imported_by = len(chunks), imported_by
            row.updated_at = datetime.now(timezone.utc)
        return {"document_id": document_id, "source": source, "chunk_count": len(chunks), "reused": False}
    finally:
        if api is not None and client is None:
            api.close()
        import_lock.release()
