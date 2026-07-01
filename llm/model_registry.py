"""可选大模型注册表 —— /model 与 build_llm 的统一来源。"""
from __future__ import annotations

import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

from config import Config


def _is_real_key(value: str | None) -> bool:
    raw = (value or "").strip()
    if not raw:
        return False
    low = raw.lower()
    if low in {"xxx", "sk-xxx", "sk-deepseek-xxx", "sk-ant-xxx", "your-api-key", "replace-me"}:
        return False
    return "xxx" not in low and "placeholder" not in low


@dataclass(frozen=True)
class ModelSpec:
    id: str
    provider: str
    label: str
    context: int
    api_name: str = ""


# 所有可通过 /model 切换的模型
MODELS: tuple[ModelSpec, ...] = (
    ModelSpec("mock", "mock", "Mock 测试", 32_000),
    ModelSpec("deepseek-v4-flash", "deepseek", "DeepSeek V4 Flash", 1_000_000),
    ModelSpec("deepseek-v4-pro", "deepseek", "DeepSeek V4 Pro", 1_000_000),
    ModelSpec("gpt-4o-mini", "openai", "GPT-4o mini", 128_000),
    ModelSpec("claude-sonnet-5", "claude", "Claude Sonnet 5", 1_000_000),
    ModelSpec("claude-sonnet-4-20250514", "claude", "Claude Sonnet 4", 200_000),
    ModelSpec("openrouter-claude-sonnet-5", "openrouter", "OpenRouter · Claude Sonnet 5", 1_000_000, "anthropic/claude-sonnet-5"),
    ModelSpec("openrouter-claude-sonnet-latest", "openrouter", "OpenRouter · Claude Sonnet Latest", 1_000_000, "~anthropic/claude-sonnet-latest"),
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
    "claude": "claude-sonnet-5",
    "openrouter": "openrouter-claude-sonnet-latest",
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


def extra_models() -> list[dict]:
    """注册表之外、用户实际配好的"聊天可用"端点(小米 MiMo / 自定义 OpenAI 兼容)。

    - 小米:用户用 VISION_* 配的(VISION_MODEL+VISION_API_KEY)→ id "ext:xiaomi"。
    - 自定义端点:model_keys.json 里非内置、且填了 key+model 的 → id "ext:<provider>"。
    这些会出现在模型下拉里,选中后由 factory 用其 base_url+key+model 直接构建 OpenAI 兼容 LLM。
    """
    out: list[dict] = []
    vm = os.environ.get("VISION_MODEL", "").strip()
    vk = (os.environ.get("VISION_API_KEY", "").strip()
          or os.environ.get("OPENAI_API_KEY", "").strip())
    if vm and _is_real_key(vk):
        out.append({"id": "ext:xiaomi", "label": f"小米 MiMo · {vm}",
                    "provider": "openai", "context": 200_000})
    try:
        from server.model_keys import ModelKeyStore
        store = ModelKeyStore(path=os.path.join(Config.LOG_DIR, "model_keys.json"))
        data = store.get_masked()
        for prov, public_cfg in data.items():
            if prov in ("deepseek", "openai", "claude", "openrouter", "xiaomi_vision", "image"):
                continue
            cfg = store.get_config(prov)
            if public_cfg.get("kind") == "chat" and _is_real_key(cfg.get("key")) and cfg.get("model"):
                out.append({"id": f"ext:{prov}",
                            "label": f"{public_cfg.get('label', prov)} · {cfg['model']}",
                            "provider": "openai", "context": 128_000})
    except Exception:
        pass
    return out


def normalize_model_id(raw: str) -> Optional[str]:
    if (raw or "").strip().lower().startswith("ext:"):
        return (raw or "").strip()      # 额外端点 id 原样透传(由 factory 解析)
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
    if spec.api_name:
        return spec.api_name
    if spec.provider == "ollama":
        return Config.OLLAMA_MODEL
    if spec.provider == "openai" and spec.id != "gpt-4o-mini":
        return spec.id
    if spec.provider == "claude" and spec.id != "claude-sonnet-4-20250514":
        return spec.id
    if spec.provider == "openrouter":
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
        return _is_real_key(os.environ.get("DEEPSEEK_API_KEY", ""))
    if p == "openai":
        return _is_real_key(os.environ.get("OPENAI_API_KEY", ""))
    if p == "openrouter":
        return _is_real_key(os.environ.get("OPENROUTER_API_KEY", ""))
    if p == "claude":
        return _is_real_key(os.environ.get("ANTHROPIC_API_KEY", ""))
    if p == "ollama":
        # 仅看是否配了地址;**不做网络探测**(探测会给每次列模型加 ~1.5s 延迟、
        # 还会放大前端竞态)。真不可用时,实际调用时再报错即可。
        return bool((Config.OLLAMA_BASE_URL or "").strip())
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
        "OpenRouter: openrouter-claude-sonnet-latest / openrouter-claude-sonnet-5",
    ]
    return "\n".join(lines)
