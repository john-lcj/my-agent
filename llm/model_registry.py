"""可选大模型注册表 —— /model 与 build_llm 的统一来源。"""
from __future__ import annotations

import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

from config import Config


@dataclass(frozen=True)
class ModelSpec:
    id: str
    provider: str
    label: str
    context: int


# 所有可通过 /model 切换的模型
MODELS: tuple[ModelSpec, ...] = (
    ModelSpec("mock", "mock", "Mock 测试", 32_000),
    ModelSpec("deepseek-v4-flash", "deepseek", "DeepSeek V4 Flash", 1_000_000),
    ModelSpec("deepseek-v4-pro", "deepseek", "DeepSeek V4 Pro", 1_000_000),
    ModelSpec("gpt-4o-mini", "openai", "GPT-4o mini", 128_000),
    ModelSpec("claude-sonnet-4-20250514", "claude", "Claude Sonnet 4", 200_000),
    ModelSpec("ollama-local", "ollama", "Ollama 本地", 128_000),
)

_BY_ID: dict[str, ModelSpec] = {m.id: m for m in MODELS}

# 兼容旧模型 / provider 名 → 模型 id
_LEGACY_ALIASES: dict[str, str] = {
    "deepseek-chat": "deepseek-v4-flash",
    "deepseek-reasoner": "deepseek-v4-pro",
}

_PROVIDER_DEFAULT: dict[str, str] = {
    "mock": "mock",
    "deepseek": "deepseek-v4-flash",
    "openai": "gpt-4o-mini",
    "claude": "claude-sonnet-4-20250514",
    "ollama": "ollama-local",
    "router": "deepseek-v4-flash",
}


def default_model_id() -> str:
    mid = normalize_model_id(getattr(Config, "MODEL", "") or "")
    if mid:
        return mid
    mid = normalize_model_id(Config.DEEPSEEK_MODEL or "")
    if mid:
        return mid
    if Config.PROVIDER in _PROVIDER_DEFAULT:
        return _PROVIDER_DEFAULT[Config.PROVIDER]
    return "deepseek-v4-flash"


def normalize_model_id(raw: str) -> Optional[str]:
    key = (raw or "").strip().lower()
    if not key:
        return None
    if key in _BY_ID:
        return key
    if key in _LEGACY_ALIASES:
        return _LEGACY_ALIASES[key]
    if key in _PROVIDER_DEFAULT:
        return _PROVIDER_DEFAULT[key]
    return None


def get_model(model_id: str | None) -> ModelSpec:
    mid = normalize_model_id(model_id or "") or default_model_id()
    return _BY_ID.get(mid) or _BY_ID["deepseek-v4-flash"]


def api_model_name(spec: ModelSpec) -> str:
    """传给 API 的 model 字段。"""
    if spec.provider == "ollama":
        return Config.OLLAMA_MODEL
    if spec.provider == "openai" and spec.id != "gpt-4o-mini":
        return spec.id
    if spec.provider == "claude" and spec.id != "claude-sonnet-4-20250514":
        return spec.id
    if spec.provider == "deepseek":
        return spec.id
    if spec.provider == "mock":
        return "mock"
    return spec.id


def list_model_ids() -> list[str]:
    return [m.id for m in MODELS]


def is_provider_configured(provider: str) -> bool:
    """该 provider 是否已配置凭证(或本地可用)。"""
    p = (provider or "").strip().lower()
    if p == "mock":
        return Config.PROVIDER == "mock"
    if p == "deepseek":
        return bool(os.environ.get("DEEPSEEK_API_KEY", "").strip())
    if p == "openai":
        return bool(os.environ.get("OPENAI_API_KEY", "").strip())
    if p == "claude":
        return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())
    if p == "ollama":
        base = (Config.OLLAMA_BASE_URL or "").rstrip("/").replace("/v1", "")
        if not base:
            return False
        try:
            urllib.request.urlopen(f"{base}/api/tags", timeout=1.5)
            return True
        except (urllib.error.URLError, OSError, ValueError):
            return False
    return False


def is_model_configured(model_id: str | None) -> bool:
    spec = get_model(model_id)
    return is_provider_configured(spec.provider)


def list_configured_models() -> list[ModelSpec]:
    return [m for m in MODELS if is_model_configured(m.id)]


def format_models_help(current_model_id: str) -> str:
    lines = [
        "可选大模型(当前会话):",
        f"  当前 → {current_model_id}",
        "",
        "  /model                列出本帮助",
        "  /model <模型id>       切换模型",
        "",
    ]
    for m in MODELS:
        mark = " ← 当前" if m.id == current_model_id else ""
        lines.append(f"  /model {m.id}{mark}")
        lines.append(f"      {m.label}")
    lines += [
        "",
        "DeepSeek 官方 API 模型: deepseek-v4-flash(默认) / deepseek-v4-pro",
    ]
    return "\n".join(lines)
