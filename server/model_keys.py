"""模型接入的服务端持久化 —— 通用 OpenAI 兼容接入 + 连通性验证状态。

每个接口存 {key, base_url, model, verified_at}:
  · 内置预设(deepseek/openai/claude/小米视觉/图像)各有默认 base_url 与 env 映射;
  · 自定义接口(任意 id)= OpenAI 兼容端点,填 base_url+key+model 即可接任意平台。
配好即写进对应环境变量,各 LLM/视觉/图像实现照常从 env 读,无需改它们。

状态三态:未配置 / 已配置(填了 key)/ 已验证(测过能通,verified_at 有值)。
安全:get_masked 永不回明文;空串或 '******' 视为"不改动"。
"""
from __future__ import annotations

import json
import os
import time

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
        "default_base_url": "", "default_model": "claude-3-5-haiku-latest",
    },
    "xiaomi_vision": {
        "label": "小米视觉(看图)", "kind": "vision", "builtin": True,
        "key_env": "VISION_API_KEY", "base_url_env": "VISION_BASE_URL", "model_env": "VISION_MODEL",
        "default_base_url": "https://api.xiaomimimo.com/v1", "default_model": "mimo-v2-omni",
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


def _norm(value) -> dict:
    """把存储值规整成 {key, base_url, model, verified_at};兼容旧的纯字符串(=key)。"""
    if isinstance(value, str):
        return {"key": value, "base_url": "", "model": "", "verified_at": 0}
    if isinstance(value, dict):
        return {"key": str(value.get("key", "")), "base_url": str(value.get("base_url", "")),
                "model": str(value.get("model", "")), "verified_at": value.get("verified_at", 0) or 0}
    return {"key": "", "base_url": "", "model": "", "verified_at": 0}


class ModelKeyStore:
    def __init__(self, path: str = "logs/model_keys.json") -> None:
        self.path = path
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._data: dict[str, dict] = self._read()
        self.apply_to_env()

    def _read(self) -> dict[str, dict]:
        if not os.path.isfile(self.path):
            return {}
        try:
            with open(self.path, encoding="utf-8") as f:
                raw = json.load(f) or {}
        except Exception:
            return {}
        return {str(p): _norm(v) for p, v in raw.items()}

    def _write(self) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

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
            if cfg.get("key") and meta.get("key_env"):
                os.environ[meta["key_env"]] = cfg["key"]
            if cfg.get("base_url") and meta.get("base_url_env"):
                os.environ[meta["base_url_env"]] = cfg["base_url"]
            if cfg.get("model") and meta.get("model_env"):
                os.environ[meta["model_env"]] = cfg["model"]

    def get_masked(self) -> dict:
        """返回每个接口的状态(不回明文)。内置预设始终出现;自定义接口附带其配置。"""
        out: dict = {}
        ids = list(PROVIDER_PRESETS.keys()) + [p for p in self._data if p not in PROVIDER_PRESETS]
        for provider in ids:
            meta = self._meta(provider)
            cfg = self._data.get(provider, {})
            key_env = meta.get("key_env", "")
            has_key = bool(cfg.get("key")) or (bool(key_env) and bool(os.environ.get(key_env, "").strip()))
            out[provider] = {
                "label": cfg.get("label") or meta.get("label", provider), "kind": meta.get("kind", "chat"),
                "builtin": meta.get("builtin", False),
                "configured": has_key,
                "verified": bool(cfg.get("verified_at")),
                "key": _MASK if cfg.get("key") else "",
                "base_url": cfg.get("base_url") or meta.get("default_base_url", ""),
                "model": cfg.get("model") or meta.get("default_model", ""),
                "default_base_url": meta.get("default_base_url", ""),
                "default_model": meta.get("default_model", ""),
            }
        return out

    def get_config(self, provider: str) -> dict:
        """取某接口的实际配置(含明文 key)——仅供服务端内部(如测试连接),不对外回。"""
        meta = self._meta(provider)
        cfg = self._data.get(provider, {})
        return {
            "key": cfg.get("key") or os.environ.get(meta.get("key_env", ""), ""),
            "base_url": cfg.get("base_url") or meta.get("default_base_url", ""),
            "model": cfg.get("model") or meta.get("default_model", ""),
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
        if key and key != _MASK:
            cfg["key"] = key
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
            self._write()
            return True
        return False

    def is_configured(self, provider: str) -> bool:
        meta = self._meta(provider)
        return bool(self._data.get(provider, {}).get("key")
                    or os.environ.get(meta.get("key_env", ""), "").strip())
