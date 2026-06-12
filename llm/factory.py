"""LLM 工厂 —— 按 model id 或 provider 建实例。"""
from __future__ import annotations

from config import Config
from llm.model_registry import api_model_name, default_model_id, get_model, normalize_model_id


def build_llm(provider: str | None = None, model: str | None = None):
    """model 优先(如 deepseek-v4-pro);否则按 provider 取默认模型。"""
    if model:
        spec = get_model(model)
    elif provider:
        mid = normalize_model_id(provider) or default_model_id()
        spec = get_model(mid)
    else:
        spec = get_model(default_model_id())

    p = spec.provider
    api_name = api_model_name(spec)

    if p == "mock":
        from llm.mock_llm import MockLLM
        return MockLLM()
    if p == "openai":
        from llm.openai_llm import OpenAILLM
        return OpenAILLM(model=api_name or Config.OPENAI_MODEL)
    if p == "claude":
        from llm.claude_llm import ClaudeLLM
        return ClaudeLLM(model=api_name or Config.CLAUDE_MODEL)
    if p == "deepseek":
        from llm.deepseek_llm import DeepSeekLLM
        return DeepSeekLLM(model=api_name)
    if p == "ollama":
        from llm.ollama_llm import OllamaLLM
        return OllamaLLM()
    if p == "router":
        from llm.router import LLMRouter
        from llm.openai_llm import OpenAILLM
        from llm.claude_llm import ClaudeLLM
        from llm.deepseek_llm import DeepSeekLLM
        from llm.ollama_llm import OllamaLLM
        flash = api_model_name(get_model("deepseek-v4-flash"))
        pro = api_model_name(get_model("deepseek-v4-pro"))
        return LLMRouter(
            {
                "openai": OpenAILLM(model=Config.OPENAI_MODEL),
                "claude": ClaudeLLM(model=Config.CLAUDE_MODEL),
                "deepseek": DeepSeekLLM(model=flash),
                "deepseek-pro": DeepSeekLLM(model=pro),
                "ollama": OllamaLLM(),
            },
            default="deepseek",
        )
    raise ValueError(f"未知 provider:{p}")
