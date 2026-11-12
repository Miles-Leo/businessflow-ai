# 模块职责：统一配置加载；环境变量优先，敏感字段使用 SecretStr。
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr
from typing import Literal

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    app_name: str = "BusinessFlow AI"
    demo_session_secret: SecretStr = SecretStr("")
    demo_session_https_only: bool = False
    database_url: str = "sqlite:///./businessflow.db"
    milvus_uri: str = "http://localhost:19530"
    milvus_collection: str = "businessflow_policy_v1"
    rag_retrieval_mode: Literal["dense", "hybrid"] = "dense"
    rag_complete_related_clauses: bool = True
    dashscope_model: str = "qwen3.8-max"
    dashscope_api_key: SecretStr = SecretStr("")
    dashscope_api_base: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    feishu_app_id: str = ""
    feishu_app_secret: SecretStr = SecretStr("")
    feishu_wiki_node_token: str = ""
    feishu_bitable_app_token: str = ""
    feishu_bitable_table_id: str = ""

@lru_cache
def get_settings() -> Settings:
    return Settings()
