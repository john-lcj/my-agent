"""Ollama 本地模型 —— OpenAI 兼容 API(/v1)。"""
from __future__ import annotations

import os

from config import Config
from llm.openai_llm import OpenAILLM


class OllamaLLM(OpenAILLM):
    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
    ) -> None:
        super().__init__(
            model=model or Config.OLLAMA_MODEL,
            api_key_env="OLLAMA_API_KEY",
            base_url=base_url or Config.OLLAMA_BASE_URL,
            name="ollama",
        )

    def _ensure_client(self):
        if self._client is not None:
            return self._client
        # Ollama 不校验 key;未设置时用占位符避免 SDK 报错。
        os.environ.setdefault(self.api_key_env, "ollama")
        return super()._ensure_client()
