"""目标接口(/api/goals)—— 从 app.py 抽出,行为不变。

GoalsStore 每次按 LOG_DIR 现取,无共享单例,抽取零风险。
"""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from config import Config


def _store():
    from memory.goals_store import GoalsStore
    return GoalsStore(path=f"{Config.LOG_DIR}/goals.json")


def register_goals(app) -> None:
    @app.get("/api/goals")
    async def list_goals() -> JSONResponse:
        return JSONResponse({"goals": _store().list()})

    @app.post("/api/goals")
    async def add_goal(request: Request) -> JSONResponse:
        b = await request.json()
        text = str(b.get("text", "")).strip()
        if not text:
            return JSONResponse({"ok": False, "error": "缺少 text"}, status_code=400)
        rec = _store().add(text, str(b.get("kind", "goal")))
        return JSONResponse({"ok": True, "goal": rec})

    @app.delete("/api/goals/{gid}")
    async def delete_goal(gid: str) -> JSONResponse:
        return JSONResponse({"ok": _store().remove(gid)})
