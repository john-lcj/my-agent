"""Model API key management shared with the settings page.

model_key.save   Save a provider key with optional base_url/model fields.
model_key.list   List configured providers without revealing secrets.
model_key.clear  Clear one provider configuration.
"""
from __future__ import annotations

from typing import Any

from capabilities.tools.base import Tool
from core.types import CapabilityResult, Risk

_STORE = None


def _store():
    global _STORE
    if _STORE is None:
        from config import Config
        from server.model_keys import ModelKeyStore
        _STORE = ModelKeyStore(path=f"{Config.LOG_DIR}/model_keys.json")
    return _STORE


class ModelKeySave(Tool):
    name = "model_key.save"
    risk = Risk.WRITE
    description = (
        "Save a model API key. Use provider ids such as deepseek, openai, claude, "
        "openrouter, or gemini. Custom OpenAI-compatible endpoints can use any id "
        "with base_url and model."
    )
    schema = {
        "type": "object",
        "properties": {
            "provider": {"type": "string", "description": "Provider id, for example deepseek"},
            "key": {"type": "string", "description": "API Key"},
            "base_url": {"type": "string", "description": "Custom endpoint URL; optional"},
            "model": {"type": "string", "description": "Default model id; optional"},
            "label": {"type": "string", "description": "Custom display name; optional"},
        },
        "required": ["provider", "key"],
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        provider = str(args.get("provider", "")).strip()
        key = str(args.get("key", "")).strip()
        if not provider or not key:
            return CapabilityResult(ok=False, error="需要 provider 和 key")
        st = _store()
        st.update(
            provider,
            key=key,
            base_url=str(args.get("base_url", "") or ""),
            model=str(args.get("model", "") or ""),
            label=str(args.get("label", "") or ""),
        )
        masked = st.get_masked().get(provider, {})
        label = masked.get("label") or provider
        return CapabilityResult(ok=True, output=f"已保存 {label} 的 API Key(已写入环境,不回显明文)。")


class ModelKeyList(Tool):
    name = "model_key.list"
    risk = Risk.READ
    description = "List configured model providers and verification state without revealing keys."
    schema = {"type": "object", "properties": {}}

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        rows = _store().get_masked()
        if not rows:
            return CapabilityResult(ok=True, output="(暂无模型接口配置)")
        lines = []
        for pid, info in rows.items():
            if not info.get("configured"):
                continue
            flag = "已验证" if info.get("verified") else "已配置"
            model = info.get("model") or info.get("default_model") or ""
            lines.append(f"- {pid} ({info.get('label', pid)}) [{flag}] model={model}")
        if not lines:
            return CapabilityResult(ok=True, output="(还没有填写任何 API Key)")
        return CapabilityResult(ok=True, output="\n".join(lines))


class ModelKeyClear(Tool):
    name = "model_key.clear"
    risk = Risk.DESTRUCTIVE
    description = "Clear the API key configuration for one provider."
    schema = {
        "type": "object",
        "properties": {"provider": {"type": "string", "description": "Provider id to clear"}},
        "required": ["provider"],
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        provider = str(args.get("provider", "")).strip()
        if not provider:
            return CapabilityResult(ok=False, error="需要 provider")
        ok = _store().clear(provider)
        return CapabilityResult(
            ok=ok,
            output=f"已清除 {provider} 的 Key" if ok else f"未找到 {provider}",
        )
