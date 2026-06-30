"""凭据保险库 API (从 app.py 抽出，行为不变)。"""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse


def register_secrets(app, vault) -> None:
    @app.get("/api/secrets")
    async def list_secrets() -> JSONResponse:
        if vault is None:
            return JSONResponse({"secrets": [], "error": "保险库不可用"})
        return JSONResponse({"secrets": vault.list()})

    @app.post("/api/secrets")
    async def save_secret(request: Request) -> JSONResponse:
        if vault is None:
            return JSONResponse({"ok": False, "error": "保险库不可用"}, status_code=503)
        b = await request.json()
        name = str(b.get("name", "")).strip()
        if not name:
            return JSONResponse({"ok": False, "error": "缺少 name"}, status_code=400)
        vault.save(name=name, secret=str(b.get("secret", "")),
                   username=str(b.get("username", "")), url=str(b.get("url", "")),
                   note=str(b.get("note", "")))
        return JSONResponse({"ok": True})

    @app.delete("/api/secrets/{name}")
    async def delete_secret(name: str) -> JSONResponse:
        if vault is None:
            return JSONResponse({"ok": False, "error": "保险库不可用"}, status_code=503)
        return JSONResponse({"ok": vault.delete(name)})
