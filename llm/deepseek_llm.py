"""DeepSeek 的 LLM 实现 —— 复用 OpenAI 兼容协议,仅换 base_url 与默认模型。"""
from __future__ import annotations

from llm.openai_llm import OpenAILLM


class DeepSeekLLM(OpenAILLM):
    def __init__(self, model: str = "deepseek-v4-flash") -> None:
        super().__init__(
            model=model,
            api_key_env="DEEPSEEK_API_KEY",
            base_url="https://api.deepseek.com",
            name="deepseek",
        )
