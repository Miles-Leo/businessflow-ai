# 模块职责：小语料 BM25 与稠密排名融合；不是外部神经网络 Reranker。
"""Small-corpus BM25 + dense reciprocal-rank fusion; no extra model service."""
from collections import Counter
import math
import re


def tokens(text: str):
    words = re.findall(r"[a-z0-9_-]+|[\u4e00-\u9fff]+", text.lower())
    result = []
    for word in words:
        if re.fullmatch(r"[\u4e00-\u9fff]+", word):
            result.extend(word[i:i + 2] for i in range(max(1, len(word) - 1)))
        else:
            result.append(word)
    return result


def hybrid_rank(question, dense_documents, corpus, top_k):
    """BM25 retrieves keyword candidates, RRF merges, overlap reranks ties."""
    if not corpus:
        return dense_documents[:top_k]
    query = set(tokens(question))
    counts = [Counter(tokens(doc.page_content)) for doc in corpus]
    avg_length = sum(sum(count.values()) for count in counts) / max(1, len(counts)) or 1
    scores = []
    for doc, count in zip(corpus, counts):
        score = 0.0
        for term in query:
            frequency = count[term]
            df = sum(term in item for item in counts)
            idf = math.log(1 + (len(counts) - df + 0.5) / (df + 0.5))
            score += idf * frequency * 2.2 / (frequency + 1.2 * (0.25 + 0.75 * sum(count.values()) / avg_length))
        if score > 0:
            scores.append((score, doc))
    lexical = [doc for _, doc in sorted(scores, key=lambda item: item[0], reverse=True)]
    merged = {}
    for ranking in (dense_documents, lexical):
        for index, doc in enumerate(ranking):
            key = doc.metadata["chunk_id"]
            if key not in merged:
                merged[key] = [doc, 0.0]
            merged[key][1] += 1 / (60 + index + 1)
    ordered = sorted(merged.values(), key=lambda item: (
        item[1], len(query.intersection(tokens(item[0].page_content))),
    ), reverse=True)
    return [doc for doc, _ in ordered[:top_k]]
