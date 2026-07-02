"""授权 + 用户认证端点 (从 app.py 抽出，行为不变)。"""
from __future__ import annotations
import os

from fastapi import Request
from fastapi.responses import JSONResponse


def register_license(app) -> None:
    @app.get("/api/license/status")
    async def license_status(request: Request) -> JSONResponse:
        try:
            from license_client.client import (
                LICENSE_KEY_ENV,
                check_license,
                get_machine_id,
                _keychain_license_key,
            )
            refresh = request.query_params.get("refresh") in {"1", "true", "yes"}
            s = check_license(force=refresh)
            machine_id = get_machine_id()
            keychain_enabled = bool(_keychain_license_key()) or bool(os.environ.get(LICENSE_KEY_ENV, ""))
            return JSONResponse({
                "ok":       True,
                "valid":    s.valid,
                "plan":     s.plan,
                "is_pro":   s.is_pro,
                "days_left": s.days_left(),
                "expires_at": s.expires_at,
                "offline":  s.offline,
                "error":    s.error,
                "machine_id": machine_id,
                "machine_id_short": machine_id[:12],
                "keychain": keychain_enabled,
            })
        except Exception as e:
            return JSONResponse({"ok": True, "valid": False, "plan": "free", "is_pro": False, "error": str(e)})

    @app.get("/api/auth/me")
    async def auth_me() -> JSONResponse:
        try:
            from license_client.client import check_license
            s = check_license()
            return JSONResponse({
                "ok":   True,
                "user": {
                    "email": "local",
                    "plan":  s.plan if s.valid else "free",
                },
            })
        except Exception:
            return JSONResponse({"ok": True, "user": {"email": "local", "plan": "free"}})

    @app.post("/api/license/activate")
    async def license_activate(request: Request) -> JSONResponse:
        try:
            body = await request.json()
            key = body.get("key", "").strip()
            if not key:
                return JSONResponse({"ok": False, "error": "请输入授权码"}, status_code=400)
            from license_client.client import activate
            s = activate(key)
            if not s.valid:
                return JSONResponse({"ok": False, "error": s.error or "激活失败"}, status_code=400)
            return JSONResponse({"ok": True, "plan": s.plan, "days_left": s.days_left(), "expires_at": s.expires_at})
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
