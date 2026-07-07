"""模型接入的服务端持久化 —— 通用 OpenAI 兼容接入 + 连通性验证状态。

每个接口存 {key, base_url, model, verified_at}:
  · 内置预设(deepseek/openai/claude/openrouter/gemini/xai/groq/qwen/kimi/智谱/perplexity/小米视觉/图像)
    各有默认 base_url 与 env 映射;
  · 自定义接口(任意 id)= OpenAI 兼容端点,填 base_url+key+model 即可接任意平台。
配好即写进对应环境变量,各 LLM/视觉/图像实现照常从 env 读,无需改它们。

状态三态:未配置 / 已配置(填了 key)/ 已验证(测过能通,verified_at 有值)。
安全:get_masked 永不回明文;空串或 '******' 视为"不改动"。
"""
from __future__ import annotations

import json
import os
import time

from server.keychain_store import delete_secret, get_secret, secret_ref, set_secret, should_use_for_path

# 内置预设:provider -> 元信息。key_env/base_url_env/model_env 为该平台对应的环境变量。
PROVIDER_PRESETS: dict[str, dict] = {
    "deepseek": {
        "label": "DeepSeek", "kind": "chat", "builtin": True,
        "key_env": "DEEPSEEK_API_KEY", "base_url_env": "DEEPSEEK_BASE_URL", "model_env": "",
        "default_base_url": "https://api.deepseek.com", "default_model": "deepseek-chat",
    },
    "openai": {
        "label": "OpenAI", "kind": "chat", "builtin": True,
        "key_env": "OPENAI_API_KEY", "base_url_env": "OPENAI_BASE_URL", "model_env": "",
        "default_base_url": "", "default_model": "gpt-4o-mini",
    },
    "claude": {
        "label": "Claude", "kind": "chat", "builtin": True,
        "key_env": "ANTHROPIC_API_KEY", "base_url_env": "", "model_env": "",
        "default_base_url": "", "default_model": "claude-sonnet-5",
    },
    "openrouter": {
        "label": "OpenRouter", "kind": "chat", "builtin": True,
        "key_env": "OPENROUTER_API_KEY", "base_url_env": "OPENROUTER_BASE_URL", "model_env": "OPENROUTER_MODEL",
        "default_base_url": "https://openrouter.ai/api/v1", "default_model": "~anthropic/claude-sonnet-latest",
    },
    "gemini": {
        "label": "Google Gemini", "kind": "chat", "builtin": True,
        "key_env": "GEMINI_API_KEY", "base_url_env": "GEMINI_BASE_URL", "model_env": "GEMINI_MODEL",
        "default_base_url": "https://generativelanguage.googleapis.com/v1beta/openai/", "default_model": "gemini-2.5-pro",
    },
    "xai": {
        "label": "xAI Grok", "kind": "chat", "builtin": True,
        "key_env": "XAI_API_KEY", "base_url_env": "XAI_BASE_URL", "model_env": "XAI_MODEL",
        "default_base_url": "https://api.x.ai/v1", "default_model": "grok-4",
    },
    "groq": {
        "label": "Groq", "kind": "chat", "builtin": True,
        "key_env": "GROQ_API_KEY", "base_url_env": "GROQ_BASE_URL", "model_env": "GROQ_MODEL",
        "default_base_url": "https://api.groq.com/openai/v1", "default_model": "llama-3.3-70b-versatile",
    },
    "qwen": {
        "label": "通义千问(Qwen)", "kind": "chat", "builtin": True,
        "key_env": "QWEN_API_KEY", "base_url_env": "QWEN_BASE_URL", "model_env": "QWEN_MODEL",
        "default_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "default_model": "qwen-plus",
    },
    "kimi": {
        "label": "Kimi / Moonshot", "kind": "chat", "builtin": True,
        "key_env": "KIMI_API_KEY", "base_url_env": "KIMI_BASE_URL", "model_env": "KIMI_MODEL",
        "default_base_url": "https://api.moonshot.cn/v1", "default_model": "moonshot-v1-8k",
    },
    "zhipu": {
        "label": "智谱 GLM", "kind": "chat", "builtin": True,
        "key_env": "ZHIPU_API_KEY", "base_url_env": "ZHIPU_BASE_URL", "model_env": "ZHIPU_MODEL",
        "default_base_url": "https://open.bigmodel.cn/api/paas/v4/", "default_model": "glm-4.5",
    },
    "perplexity": {
        "label": "Perplexity", "kind": "chat", "builtin": True,
        "key_env": "PERPLEXITY_API_KEY", "base_url_env": "PERPLEXITY_BASE_URL", "model_env": "PERPLEXITY_MODEL",
        "default_base_url": "https://api.perplexity.ai", "default_model": "sonar-pro",
    },
    "xiaomi_vision": {
        "label": "小米视觉(看图)", "kind": "vision", "builtin": True,
        "key_env": "VISION_API_KEY", "base_url_env": "VISION_BASE_URL", "model_env": "VISION_MODEL",
        "default_base_url": "https://api.xiaomimimo.com/v1", "default_model": "mimo-v2.5-pro",
    },
    "image": {
        "label": "图像生成", "kind": "image", "builtin": True,
        "key_env": "IMAGE_API_KEY", "base_url_env": "IMAGE_BASE_URL", "model_env": "IMAGE_MODEL",
        "default_base_url": "", "default_model": "",
    },
}

# 向后兼容:旧代码/端点引用的 provider->key_env 映射。
PROVIDER_KEY_ENV: dict[str, str] = {p: m["key_env"] for p, m in PROVIDER_PRESETS.items()}

_MASK = "******"


def migrate_mimo_model(model: str) -> str:
    """MiMo-V2 系列已下线(2026-06);旧配置自动映射到 V2.5。"""
    m = (model or "").strip()
    if not m:
        return m
    if m == "mimo-v2-omni" or (m.startswith("mimo-v2") and not m.startswith("mimo-v2.5")):
        return "mimo-v2.5-pro"
    return m


def is_real_key(value: str | None) -> bool:
    """Return False for empty values and common documentation placeholders."""
    raw = (value or "").strip()
    if not raw or raw == _MASK:
        return False
    low = raw.lower()
    placeholders = {
        "xxx",
        "sk-xxx",
        "sk-deepseek-xxx",
        "sk-ant-xxx",
        "your-api-key",
        "your_api_key",
        "replace-me",
        "replace_me",
        "填入你的key",
    }
    if low in placeholders:
        return False
    return "xxx" not in low and "placeholder" not in low


def _norm(value) -> dict:
    """把存储值规整成 {key, base_url, model, verified_at};兼容旧的纯字符串(=key)。"""
    if isinstance(value, str):
        return {"key": value, "base_url": "", "model": "", "verified_at": 0, "label": ""}
    if isinstance(value, dict):
        return {"key": str(value.get("key", "")), "base_url": str(value.get("base_url", "")),
                "model": str(value.get("model", "")), "verified_at": value.get("verified_at", 0) or 0,
                "label": str(value.get("label", ""))}
    return {"key": "", "base_url": "", "model": "", "verified_at": 0, "label": ""}


class ModelKeyStore:
    def __init__(self, path: str = "logs/model_keys.json") -> None:
        self.path = path
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self.use_keychain = should_use_for_path(path)
        self._data: dict[str, dict] = self._read()
        self._migrate_plaintext_keys_to_keychain()
        self.apply_to_env()

    def _read(self) -> dict[str, dict]:
        if not os.path.isfile(self.path):
            return {}
        try:
            with open(self.path, encoding="utf-8") as f:
                raw = json.load(f) or {}
        except Exception:
            return {}
        data = {str(p): _norm(v) for p, v in raw.items()}
        if self.use_keychain:
            for provider, cfg in data.items():
                stored = get_secret(secret_ref("model", provider))
                if stored:
                    cfg["key"] = stored
        return data

    def _write(self) -> None:
        payload = self._data
        if self.use_keychain:
            payload = {}
            for provider, cfg in self._data.items():
                safe = dict(cfg)
                safe["key"] = ""
                payload[provider] = safe
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def _migrate_plaintext_keys_to_keychain(self) -> None:
        if not self.use_keychain:
            return
        changed = False
        for provider, cfg in list(self._data.items()):
            key = cfg.get("key", "")
            if is_real_key(key) and set_secret(secret_ref("model", provider), key):
                cfg["key"] = ""
                changed = True
        if changed:
            self._write()

    def _meta(self, provider: str) -> dict:
        """内置预设元信息;自定义接口给一套通用元信息。"""
        if provider in PROVIDER_PRESETS:
            return PROVIDER_PRESETS[provider]
        return {"label": provider, "kind": "chat", "builtin": False,
                "key_env": "", "base_url_env": "", "model_env": "",
                "default_base_url": "", "default_model": ""}

    def apply_to_env(self) -> None:
        """把每个已配置接口写进对应环境变量(以网页配置为准)。"""
        for provider, cfg in self._data.items():
            meta = self._meta(provider)
            key = cfg.get("key")
            if self.use_keychain:
                key = key if is_real_key(key) else get_secret(secret_ref("model", provider))
            if is_real_key(key) and meta.get("key_env"):
                os.environ[meta["key_env"]] = key
            if cfg.get("base_url") and meta.get("base_url_env"):
                os.environ[meta["base_url_env"]] = cfg["base_url"]
            if cfg.get("model") and meta.get("model_env"):
                os.environ[meta["model_env"]] = migrate_mimo_model(cfg["model"])

    def get_masked(self) -> dict:
        """返回每个接口的状态(不回明文)。内置预设始终出现;自定义接口附带其配置。"""
        out: dict = {}
        ids = list(PROVIDER_PRESETS.keys()) + [p for p in self._data if p not in PROVIDER_PRESETS]
        for provider in ids:
            meta = self._meta(provider)
            cfg = self._data.get(provider, {})
            if self.use_keychain:
                kc_key = get_secret(secret_ref("model", provider))
                if kc_key:
                    cfg = {**cfg, "key": kc_key}
            key_env = meta.get("key_env", "")
            has_key = is_real_key(cfg.get("key")) or (
                bool(key_env) and is_real_key(os.environ.get(key_env, ""))
            )
            out[provider] = {
                "label": cfg.get("label") or meta.get("label", provider), "kind": meta.get("kind", "chat"),
                "builtin": meta.get("builtin", False),
                "configured": has_key,
                "verified": bool(cfg.get("verified_at")),
                "key": _MASK if has_key else "",
                "base_url": cfg.get("base_url") or meta.get("default_base_url", ""),
                "model": migrate_mimo_model(cfg.get("model") or meta.get("default_model", "")),
                "default_base_url": meta.get("default_base_url", ""),
                "default_model": meta.get("default_model", ""),
            }
        return out

    def get_config(self, provider: str) -> dict:
        """取某接口的实际配置(含明文 key)——仅供服务端内部(如测试连接),不对外回。"""
        meta = self._meta(provider)
        cfg = self._data.get(provider, {})
        if self.use_keychain:
            kc_key = get_secret(secret_ref("model", provider))
            if kc_key:
                cfg = {**cfg, "key": kc_key}
        stored_key = cfg.get("key")
        env_key = os.environ.get(meta.get("key_env", ""), "")
        return {
            "key": stored_key if is_real_key(stored_key) else (env_key if is_real_key(env_key) else ""),
            "base_url": cfg.get("base_url") or meta.get("default_base_url", ""),
            "model": migrate_mimo_model(cfg.get("model") or meta.get("default_model", "")),
            "kind": meta.get("kind", "chat"),
        }

    def update(self, provider: str, key: str = "", base_url: str = "",
               model: str = "", label: str = "") -> None:
        """新增/更新一个接口。key 为空或 '******' 表示不改动 key(保留原值)。"""
        provider = (provider or "").strip()
        if not provider:
            return
        cfg = self._data.get(provider, {"key": "", "base_url": "", "model": "", "verified_at": 0})
        key = "" if key is None else str(key).strip()
        if is_real_key(key):
            cfg["key"] = key
            if self.use_keychain and set_secret(secret_ref("model", provider), key):
                cfg["key"] = ""
            cfg["verified_at"] = 0   # 换了 key,验证状态作废
        if base_url is not None and str(base_url).strip():
            cfg["base_url"] = str(base_url).strip()
        if model is not None and str(model).strip():
            cfg["model"] = str(model).strip()
        # 自定义接口记下展示名
        if label and provider not in PROVIDER_PRESETS:
            cfg["label"] = str(label).strip()
        self._data[provider] = cfg
        self._write()
        self.apply_to_env()

    def update_many(self, values: dict) -> None:
        """兼容旧入参:{"deepseek": "sk-...", ...} 只更新 key。"""
        for p, k in (values or {}).items():
            self.update(p, key=k)

    def mark_verified(self, provider: str, ok: bool) -> None:
        cfg = self._data.get(provider)
        if cfg is not None:
            cfg["verified_at"] = time.time() if ok else 0
            self._write()

    def clear(self, provider: str) -> bool:
        if provider in self._data:
            del self._data[provider]
            if self.use_keychain:
                delete_secret(secret_ref("model", provider))
            self._write()
            return True
        return False

    def is_configured(self, provider: str) -> bool:
        meta = self._meta(provider)
        stored = self._data.get(provider, {}).get("key")
        if self.use_keychain and not is_real_key(stored):
            stored = get_secret(secret_ref("model", provider))
        return bool(is_real_key(stored)
                    or is_real_key(os.environ.get(meta.get("key_env", ""), "")))
