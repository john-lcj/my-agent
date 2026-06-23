"""DeepSeek 的 LLM 实现 —— 复用 OpenAI 兼容协议,仅换 base_url 与默认模型。"""
from __future__ import annotations

import os

from llm.openai_llm import OpenAILLM


class DeepSeekLLM(OpenAILLM):
    def __init__(self, model: str = "deepseek-v4-flash",
                 api_key: str | None = None, api_keys: list | None = None) -> None:
        super().__init__(
            model=model,
            api_key_env="DEEPSEEK_API_KEY",
            # 允许 DEEPSEEK_BASE_URL 覆盖(默认官方端点)。
            base_url=os.environ.get("DEEPSEEK_BASE_URL", "").strip() or "https://api.deepseek.com",
            name="deepseek",
            api_key=api_key,
            api_keys=api_keys,
        )
