"""模型、运行时配置、API key 管理端点 (从 app.py 抽出，行为不变)。"""
from __future__ import annotations
import os
import socket
from urllib.parse import urlparse

from fastapi import Request
from fastapi.responses import JSONResponse

from config import Config


def register_models(app, runtime_cfg, model_keys, longterm) -> None:

    @app.get("/api/models")
    async def list_models_api(all: bool = False, current: str = "") -> JSONResponse:
        from llm.model_registry import MODELS, is_model_configured, normalize_model_id
        cur = normalize_model_id(current) if current else None
        key_states = model_keys.get_masked()

        def _ollama_reachable() -> bool:
            target = urlparse(Config.OLLAMA_BASE_URL or "http://127.0.0.1:11434")
            host = target.hostname or "127.0.0.1"
            port = target.port or (443 if target.scheme == "https" else 80)
            try:
                with socket.create_connection((host, port), timeout=0.15):
                    return True
            except OSError:
                return False

        ollama_ready = _ollama_reachable()

        def _state(model_id: str, provider: str, configured: bool) -> dict:
            key_provider = provider
            if model_id.startswith("ext:"):
                key_provider = model_id[4:]
                if key_provider == "xiaomi":
                    key_provider = "xiaomi_vision"
            verified = bool((key_states.get(key_provider) or {}).get("verified"))
            if provider == "mock":
                verified = configured
            elif provider == "ollama":
                verified = configured and ollama_ready
            return {"configured": configured, "verified": verified,
                    "available": configured and verified}

        out = []
        seen: set[str] = set()
        for m in MODELS:
            configured = is_model_configured(m.id)
            if all or configured or (cur and m.id == cur):
                out.append({"id": m.id, "label": m.label, "provider": m.provider,
                             "context": m.context,
                             **_state(m.id, m.provider, configured)})
                seen.add(m.id)
        if cur and cur not in seen:
            spec = next((m for m in MODELS if m.id == cur), None)
            if spec:
                configured = is_model_configured(spec.id)
                out.insert(0, {"id": spec.id, "label": spec.label, "provider": spec.provider,
                                "context": spec.context,
                                **_state(spec.id, spec.provider, configured)})
        from llm.model_registry import extra_models
        for em in extra_models():
            if em["id"] not in seen:
                out.append({**em, **_state(em["id"], em["provider"], True)})
                seen.add(em["id"])
        return JSONResponse({"models": out})

    @app.get("/api/config")
    async def get_runtime_config() -> JSONResponse:
        cfg = runtime_cfg.load()
        model_id = runtime_cfg.get_model()
        return JSONResponse({
            "model":          model_id,
            "provider":       cfg.get("provider", runtime_cfg.get_provider()),
            "max_cost_usd":   cfg.get("max_cost_usd", Config.MAX_COST_USD),
            "governance_mode": cfg.get("governance_mode", Config.GOVERNANCE_MODE),
            "max_steps":      cfg.get("max_steps", Config.MAX_STEPS),
            "vision_model":   cfg.get("vision_model", os.environ.get("VISION_MODEL", "")),
            "proactive":      runtime_cfg.get_proactive(),
            "briefing_enabled": runtime_cfg.get_briefing_enabled(),
            "briefing_at":      runtime_cfg.get_briefing_at(),
        })

    @app.post("/api/config")
    async def save_runtime_config(request: Request) -> JSONResponse:
        from llm.model_registry import get_model, normalize_model_id
        body = await request.json()
        allowed = {k: body[k] for k in ("max_cost_usd", "governance_mode", "vision_model") if k in body}
        if "vision_model" in allowed:
            os.environ["VISION_MODEL"] = str(allowed["vision_model"] or "").strip()
        if "max_steps" in body or "maxSteps" in body:
            raw = body.get("max_steps", body.get("maxSteps"))
            try:
                allowed["max_steps"] = max(0, int(raw)) if str(raw).strip() != "" else 0
            except (TypeError, ValueError):
                allowed["max_steps"] = 0
        if "proactive" in body:
            allowed["proactive"] = bool(body.get("proactive"))
        if "briefing_enabled" in body:
            allowed["briefing_enabled"] = bool(body.get("briefing_enabled"))
        if "briefing_at" in body:
            allowed["briefing_at"] = str(body.get("briefing_at") or "08:00").strip()
        if "model" in body:
            mid = normalize_model_id(str(body["model"]))
            if mid:
                allowed["model"] = mid
                allowed["provider"] = get_model(mid).provider
        elif "provider" in body:
            mid = normalize_model_id(str(body["provider"]))
            if mid:
                allowed["model"] = mid
                allowed["provider"] = get_model(mid).provider
        saved = runtime_cfg.save(allowed)
        return JSONResponse({"ok": True, "config": saved})

    @app.get("/api/keys")
    async def get_model_keys() -> JSONResponse:
        return JSONResponse({"keys": model_keys.get_masked()})

    @app.post("/api/keys")
    async def save_model_keys(request: Request) -> JSONResponse:
        body = await request.json()
        if body.get("values") is not None:
            model_keys.update_many(body["values"])
        elif body.get("provider"):
            model_keys.update(body["provider"], key=body.get("key", ""),
                              base_url=body.get("base_url", ""), model=body.get("model", ""),
                              label=body.get("label", ""))
        return JSONResponse({"ok": True, "keys": model_keys.get_masked()})

    @app.post("/api/models/test")
    async def test_model_endpoint(request: Request) -> JSONResponse:
        from server.model_test import test_endpoint
        b = await request.json()
        provider = (b.get("provider") or "").strip()
        cfg = model_keys.get_config(provider) if provider else {}
        key = b.get("key") or cfg.get("key", "")
        if key in ("", "******"):
            key = cfg.get("key", "")
        base_url = b.get("base_url") or cfg.get("base_url", "")
        model = b.get("model") or cfg.get("model", "")
        kind = b.get("kind") or cfg.get("kind", "chat")
        sdk = "anthropic" if provider == "claude" else "openai"
        result = await test_endpoint(sdk, kind, base_url, key, model)
        if provider:
            model_keys.mark_verified(provider, bool(result.get("ok")))
        return JSONResponse(result)

    @app.delete("/api/keys/{provider}")
    async def delete_model_key(provider: str) -> JSONResponse:
        ok = model_keys.clear(provider)
        return JSONResponse({"ok": ok, "keys": model_keys.get_masked()})

    @app.get("/api/memory/preferences")
    async def list_preferences() -> JSONResponse:
        rows = longterm.list_by_kind("preference", limit=100)
        return JSONResponse({"preferences": rows})

    @app.delete("/api/memory/preferences/{pref_id}")
    async def delete_preference(pref_id: int) -> JSONResponse:
        rows = longterm.list_by_kind("preference", limit=1000)
        target = next((r for r in rows if r["id"] == pref_id), None)
        if target is None:
            return JSONResponse({"ok": False, "error": "未找到该偏好"}, status_code=404)
        n = longterm.delete_by_content("preference", target["content"])
        return JSONResponse({"ok": n > 0, "deleted": n})
