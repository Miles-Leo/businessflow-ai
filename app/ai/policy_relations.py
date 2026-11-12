# 模块职责：限定演示政策的条款关联补齐；不跨文档、跨生效版本补造依据。
"""Explicit, bounded relations for the demo policy; never invent missing clauses."""
import json
from langchain_core.documents import Document

POLICY_SOURCE = "knowledge/after_sales_policy.md"
POLICY_TITLE = "BusinessFlow AI 虚构企业售后政策"


def complete_policy_context(documents, client, active, legacy_collection, top_k):
    """Keep AS-04 with its definition and approval boundary within the same version.

    Related rows are fetched from Milvus, not copied from a potentially stale local
    Markdown. Non-demo documents are unaffected. top_k is still a hard limit.
    """
    if top_k < 2:
        return documents[:top_k]
    anchors = [d for d in documents if d.metadata.get("source", "").replace("\\", "/") == POLICY_SOURCE
               and d.metadata.get("document_title") == POLICY_TITLE and d.metadata.get("section", "").startswith("AS-04")]
    if not anchors:
        return documents[:top_k]
    anchor = anchors[0]
    source = anchor.metadata["source"]
    collection = next((r["collection"] for r in active if r["source"].replace("\\", "/") == POLICY_SOURCE), legacy_collection)
    related = [d for d in documents if d.metadata.get("source") == source
               and d.metadata.get("document_title") == POLICY_TITLE
               and d.metadata.get("section", "")[:5] in {"AS-02", "AS-05"}]
    present = {d.metadata["section"][:5] for d in related}
    missing = {"AS-02", "AS-05"} - present
    if missing:
        conditions = " or ".join(f"section like {json.dumps(code + '%')}" for code in sorted(missing))
        rows = client.query(collection_name=collection,
                            filter=f"source == {json.dumps(source, ensure_ascii=False)} and document_title == {json.dumps(POLICY_TITLE, ensure_ascii=False)} and ({conditions})",
                            output_fields=["chunk_id", "text", "source", "document_title", "section"], limit=10)
        for row in rows:
            # Validate returned rows as well: stale/cross-document data must not enter context.
            if row.get("source") != source or row.get("document_title") != POLICY_TITLE or row.get("section", "")[:5] not in missing:
                continue
            related.append(Document(page_content=row["text"], metadata={
                "chunk_id": row["chunk_id"], "source": source, "document_title": POLICY_TITLE,
                "section": row["section"], "score": 0.0, "retrieval_method": "related_clause",
            }))
    # Preserve the original dense/hybrid ranking for remaining slots.
    # The explicit approval boundary is prioritized when the budget only has 2 slots.
    ordered = [anchor, *sorted(related, key=lambda d: 0 if d.metadata["section"].startswith("AS-05") else 1), *documents]
    result, seen = [], set()
    for doc in ordered:
        key = (doc.metadata.get("source", "").replace("\\", "/"), doc.metadata["chunk_id"])
        if key not in seen:
            result.append(doc)
            seen.add(key)
        if len(result) == top_k:
            break
    return result
