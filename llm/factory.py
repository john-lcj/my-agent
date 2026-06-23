"""LLM 工厂 —— 按 model id 或 provider 建实例。"""
from __future__ import annotations

from config import Config
from llm.model_registry import api_model_name, default_model_id, get_model, normalize_model_id


def deepseek_key_pool() -> list[str]:
    """DeepSeek key 池:DEEPSEEK_API_KEY + DEEPSEEK_API_KEY_2/3/...,或逗号分隔的
    DEEPSEEK_API_KEYS。用于把并行子代理分散到多个 key,绕开单 key 的并发/限流上限。"""
    import os
    keys: list[str] = []
    multi = os.environ.get("DEEPSEEK_API_KEYS", "").strip()
    if multi:
        keys += [k.strip() for k in multi.split(",") if k.strip()]
    for name in ("DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY_2", "DEEPSEEK_API_KEY_3",
                 "DEEPSEEK_API_KEY_4", "DEEPSEEK_API_KEY_5"):
        v = os.environ.get(name, "").strip()
        if v:
            keys.append(v)
    seen, out = set(), []
    for k in keys:
        if k not in seen:
            seen.add(k); out.append(k)
    return out


def role_model_id(role: str) -> str:
    """某"角色"(judge 质检 / reflect 反思)该用的模型 id。

    读环境变量 AGENT_<ROLE>_MODEL;值为 'main'/'same'/空 表示"和主模型一样"(返回 '')。
    服务端会在非 mock 部署时把 judge/reflect 默认设成 deepseek-v4-pro(=reasoner 档),
    让"判断"用更会想的脑子,执行仍用便宜的主模型——好钢用在刀刃上。
    """
    import os
    mid = os.environ.get(f"AGENT_{role.upper()}_MODEL", "").strip()
    if not mid or mid.lower() in ("main", "same", "off"):
        return ""
    return mid


def build_role_llm(role: str):
    """按角色构建 LLM;未配置(返回 '')时给 None,调用方回退到主模型。"""
    mid = role_model_id(role)
    if not mid:
        return None
    try:
        return build_llm(model=mid)
    except Exception:
        return None


def _fallback_model_ids() -> list[str]:
    """AGENT_FALLBACK_MODELS="id1,id2" → 备用模型 id 列表(主模型失败时按序回退)。"""
    import os
    raw = os.environ.get("AGENT_FALLBACK_MODELS", "").strip()
    return [m.strip() for m in raw.split(",") if m.strip()]


def build_llm(provider: str | None = None, model: str | None = None,
              api_key: str | None = None, with_fallback: bool = True):
    """model 优先(如 deepseek-v4-pro);否则按 provider 取默认模型。
    api_key:显式指定(用于子代理 key 池);为空则各 provider 从环境变量读。
    with_fallback:配了 AGENT_FALLBACK_MODELS 时,把主模型包成失败回退链。"""
    primary = _build_single(provider, model, api_key)
    if not with_fallback:
        return primary
    backups_ids = _fallback_model_ids()
    if not backups_ids or getattr(primary, "name", "") == "mock":
        return primary
    backups = []
    for mid in backups_ids:
        try:
            backups.append(_build_single(None, mid, None))
        except Exception:
            continue
    if not backups:
        return primary
    from llm.fallback import FallbackLLM
    return FallbackLLM(primary, backups)


def _build_ext_llm(model_id: str):
    """解析 ext:<provider> → 用其 base_url+key+model 直接构建 OpenAI 兼容 LLM。

    ext:xiaomi → 读 VISION_*(用户用视觉那套配的小米);其余 ext:<prov> → 读 model_keys.json。
    """
    import json
    import os as _os
    from config import Config
    prov = model_id[len("ext:"):]
    if prov == "xiaomi":
        key = (_os.environ.get("VISION_API_KEY", "").strip()
               or _os.environ.get("OPENAI_API_KEY", "").strip())
        base = _os.environ.get("VISION_BASE_URL", "").strip() or None
        mname = _os.environ.get("VISION_MODEL", "").strip()
    else:
        v: dict = {}
        try:
            path = _os.path.join(Config.LOG_DIR, "model_keys.json")
            data = json.load(open(path, encoding="utf-8")) if _os.path.isfile(path) else {}
            raw = data.get(prov) or {}
            v = raw if isinstance(raw, dict) else {"key": raw}
        except Exception:
            v = {}
        key = str(v.get("key", "")).strip()
        base = (str(v.get("base_url", "")).strip() or None)
        mname = str(v.get("model", "")).strip()
    if not key or not mname:
        raise ValueError(f"模型接入「{prov}」不完整(缺 API Key 或模型名),请在「模型接入」里补全")
    from llm.openai_llm import OpenAILLM
    return OpenAILLM(model=mname, base_url=base, api_key=key, name=f"ext:{prov}")


def _build_single(provider: str | None = None, model: str | None = None, api_key: str | None = None):
    if model and model.startswith("ext:"):
        return _build_ext_llm(model)
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
        import os as _os
        from llm.openai_llm import OpenAILLM
        # OPENAI_BASE_URL 可指向任意 OpenAI 兼容端点(Kimi/通义/智谱/本地…)。
        return OpenAILLM(model=api_name or Config.OPENAI_MODEL,
                         base_url=_os.environ.get("OPENAI_BASE_URL", "").strip() or None)
    if p == "claude":
        from llm.claude_llm import ClaudeLLM
        return ClaudeLLM(model=api_name or Config.CLAUDE_MODEL)
    if p == "deepseek":
        from llm.deepseek_llm import DeepSeekLLM
        # 显式 api_key 优先;否则自动用 key 池(多 key 时按调用轮换,绕开单 key 并发上限)。
        return DeepSeekLLM(model=api_name, api_key=api_key,
                           api_keys=None if api_key else deepseek_key_pool())
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
