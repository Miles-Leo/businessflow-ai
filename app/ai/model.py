# 模块职责：百炼兼容接口的统一模型工厂；模型名来自配置，凭证不进入日志。
import os
from app.core.config import get_settings
from langchain.chat_models import init_chat_model



def create_chat_model():
    # 初始化模型
    model = init_chat_model(
        model=get_settings().dashscope_model,
        model_provider="openai",
        api_key=os.environ.get("DASHSCOPE_API_KEY") or get_settings().dashscope_api_key.get_secret_value(),
        base_url=os.environ.get("DASHSCOPE_API_BASE") or get_settings().dashscope_api_base,
        timeout=30,
        max_retries=0,
    )

    return model
