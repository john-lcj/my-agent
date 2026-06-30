"""用户档案 + 版本号端点 (从 app.py 抽出，行为不变)。"""
from __future__ import annotations
import os

from fastapi import Request
from fastapi.responses import JSONResponse


def register_profile(app) -> None:
    @app.get("/api/version")
    async def version() -> JSONResponse:
        try:
            vf = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__)))), "VERSION")
            ver = open(vf).read().strip() if os.path.exists(vf) else "unknown"
        except Exception:
            ver = "unknown"
        return JSONResponse({"version": ver})

    @app.get("/api/profile")
    async def get_profile() -> JSONResponse:
        try:
            from core.persona import load_owner
            owner = load_owner()
            return JSONResponse({"ok": True, "profile": {
                "name":        owner.get("name", ""),
                "call_me":     owner.get("call_me", ""),
                "about":       owner.get("about", ""),
                "preferences": owner.get("preferences", []),
            }})
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    @app.post("/api/profile")
    async def save_profile(request: Request) -> JSONResponse:
        try:
            from core.persona import save_owner
            body = await request.json()
            prefs = body.get("preferences", [])
            if isinstance(prefs, str):
                prefs = [p.strip() for p in prefs.splitlines() if p.strip()]
            owner = {
                "name":        body.get("name", ""),
                "call_me":     body.get("call_me", ""),
                "about":       body.get("about", ""),
                "preferences": prefs,
            }
            save_owner(owner)
            return JSONResponse({"ok": True})
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
