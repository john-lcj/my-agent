"""变化监控接口(/api/monitors)—— 从 app.py 抽出,行为不变。"""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from config import Config


def _store():
    from memory.monitor_store import MonitorStore
    return MonitorStore(path=f"{Config.LOG_DIR}/monitors.json")


def register_monitors(app) -> None:
    @app.get("/api/monitors")
    async def list_monitors() -> JSONResponse:
        return JSONResponse({"monitors": _store().list()})

    @app.post("/api/monitors")
    async def create_monitor(request: Request) -> JSONResponse:
        b = await request.json()
        source = str(b.get("source", "")).strip()
        action = str(b.get("action", "")).strip()
        if not source or not action:
            return JSONResponse({"ok": False, "error": "需要 source 和 action"}, status_code=400)
        rec = _store().create(
            name=str(b.get("name", "")), source_type=str(b.get("source_type", "url")),
            source=source, action=action, interval_sec=int(b.get("interval_sec", 1800) or 1800))
        return JSONResponse({"ok": True, "monitor": rec})

    @app.delete("/api/monitors/{mid}")
    async def delete_monitor(mid: str) -> JSONResponse:
        return JSONResponse({"ok": _store().delete(mid)})
