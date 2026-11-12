# 模块职责：统一创建文本向量模型；供知识导入与查询使用。
import os
from langchain_openai import OpenAIEmbeddings
from app.core.config import get_settings


def create_embeddings() -> OpenAIEmbeddings:

    return OpenAIEmbeddings(
        model="text-embedding-v4",
        api_key=os.environ.get("DASHSCOPE_API_KEY") or get_settings().dashscope_api_key.get_secret_value(),
        base_url=os.environ.get("DASHSCOPE_API_BASE") or get_settings().dashscope_api_base,
        dimensions=1024,
        check_embedding_ctx_length=False,
        request_timeout=30,
        max_retries=0,
    )
