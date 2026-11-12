# 模块职责：政策加载、分块、检索与回答；只从当前生效版本获取依据。

from pathlib import Path
from langchain_core.documents import Document
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_text_splitters import MarkdownHeaderTextSplitter
from app.ai.embedding import create_embeddings
from pymilvus import MilvusClient
from app.ai.prompts import POLICY_QA_SYSTEM_PROMPT
from app.ai.model import create_chat_model
from app.core.config import get_settings



#加载 Markdown 文档
def load_markdown(path: Path) -> Document:


    text = path.read_text(encoding="utf-8")
    return Document(page_content=text, metadata={"source": str(path)})


# 分割 Markdown 文档
def split_markdown(document: Document) -> list[Document]:


    #切分依据:
    headers_to_split_on = [
        ("#", "document_title"),
        ("##", "section"),
    ]

    # 创建切分器
    markdown_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on)

    # 切分文档
    documents = markdown_splitter.split_text(document.page_content)
    for chunk in documents:
        chunk.metadata = {
            **document.metadata,
            **chunk.metadata,
        }

    return documents


# 维护约束：过滤已替换的旧知识版本，再融合排名与关联条款；最终关闭连接。
def retrieve_policy(
    question: str,
    top_k: int = 3,
) -> list[Document]:



    client = MilvusClient(uri=get_settings().milvus_uri)

    try:
        embeddings = create_embeddings()
        query_vector = embeddings.embed_query(question)
        from app.services.knowledge_import import active_documents
        active = active_documents()
        results = client.search(
            collection_name=get_settings().milvus_collection,
            data=[query_vector],
            anns_field="embedding",
            limit=top_k,
            search_params={"metric_type": "COSINE"},
            output_fields=["text", "source", "document_title", "section"],
        ) if not active or client.has_collection(collection_name=get_settings().milvus_collection) else [[]]

        documents = []
        #转换成Document列表
        for hit in results[0]:
            entity = hit["entity"]
            document = Document(
                page_content=entity["text"],
                metadata={
                    "source": entity["source"],
                    "document_title": entity["document_title"],
                    "section": entity["section"],
                    "chunk_id": hit["chunk_id"],
                    "score": hit["distance"],
                },
            )
            documents.append(document)

        replaced = {row["source"].replace("\\", "/") for row in active}
        documents = [doc for doc in documents if doc.metadata["source"].replace("\\", "/") not in replaced]
        for row in active:
            hits = client.search(collection_name=row["collection"], data=[query_vector], anns_field="embedding",
                                 limit=top_k, search_params={"metric_type": "COSINE"},
                                 output_fields=["text", "source", "document_title", "section"])
            for hit in hits[0]:
                entity = hit["entity"]
                documents.append(Document(page_content=entity["text"], metadata={
                    "source": entity["source"], "document_title": entity["document_title"],
                    "section": entity["section"], "chunk_id": hit.get("chunk_id", hit.get("id")), "score": hit["distance"],
                }))
        documents = sorted(documents, key=lambda doc: doc.metadata["score"], reverse=True)
        if get_settings().rag_retrieval_mode == "hybrid":
            from app.ai.ranking import hybrid_rank
            corpus = []
            collections = [row["collection"] for row in active]
            legacy = get_settings().milvus_collection
            if client.has_collection(collection_name=legacy):
                collections.append(legacy)
            for collection in collections:
                rows = client.query(collection_name=collection, filter="chunk_id != ''", limit=1000,
                                    output_fields=["chunk_id", "text", "source", "document_title", "section"])
                for row in rows:
                    if collection == legacy and row["source"].replace("\\", "/") in replaced:
                        continue
                    corpus.append(Document(page_content=row["text"], metadata={
                        "chunk_id": row["chunk_id"], "source": row["source"], "document_title": row["document_title"],
                        "section": row["section"], "score": 0.0,
                    }))
            documents = hybrid_rank(question, documents, corpus, top_k)
        if get_settings().rag_complete_related_clauses:
            from app.ai.policy_relations import complete_policy_context
            return complete_policy_context(documents, client, active, get_settings().milvus_collection, top_k)
        return documents[:top_k]

    finally:
        client.close()



# 整理成上下文文档
def format_policy_context(documents: list[Document]) -> str:


    parts = []
    for i, doc in enumerate(documents, start=1):
        parts.append(f"[{i}]\n"
                    f"文档:{doc.metadata['document_title']}\n"
                    f"条款:{doc.metadata['section']}\n"
                    f"来源:{doc.metadata['source']}\n"
                    f"正文:\n {doc.page_content}\n")

    return "\n\n".join(parts)

# 回答政策问题
def answer_policy_question(
    question: str,
    top_k: int = 5,
) -> dict[str, object]:




    documents = retrieve_policy(question, top_k=top_k)
    if not documents:
        return {"answer": "未找到相关政策,现有信息不足以回答", "sources": []}

    context = format_policy_context(documents)
    model = create_chat_model()
    messages = [
        SystemMessage(content=POLICY_QA_SYSTEM_PROMPT),
        HumanMessage(
            content=f"问题：{question}\n\n政策参考片段：\n{context}"
        ),
    ]
    response = model.invoke(messages)

    sources = []

    for index, doc in enumerate(documents, start=1):
        sources.append({
            "citation_id": index,
            "chunk_id": doc.metadata["chunk_id"],
            "document_title": doc.metadata["document_title"],
            "section": doc.metadata["section"],
            "source": doc.metadata["source"],
            "score": doc.metadata["score"],
        })


    return {
    "answer": response.content,
    "sources": sources,
    }
