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

    @app.get("/api/goals/graph")
    async def goal_graph() -> JSONResponse:
        return JSONResponse(_store().graph())

    @app.post("/api/goals")
    async def add_goal(request: Request) -> JSONResponse:
        b = await request.json()
        text = str(b.get("text", "")).strip()
        if not text:
            return JSONResponse({"ok": False, "error": "缺少 text"}, status_code=400)
        rec = _store().add(
            text,
            str(b.get("kind", "goal")),
            owner=str(b.get("owner", "owner")),
            deadline=str(b.get("deadline", "")),
            status=str(b.get("status", "active")),
        )
        return JSONResponse({"ok": True, "goal": rec})

    @app.post("/api/goals/link")
    async def link_goals(request: Request) -> JSONResponse:
        b = await request.json()
        try:
            edge = _store().link(
                str(b.get("source", "")).strip(),
                str(b.get("target", "")).strip(),
                str(b.get("relation", "contains")).strip(),
            )
        except (KeyError, ValueError) as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        return JSONResponse({"ok": True, "edge": edge})

    @app.delete("/api/goals/{gid}")
    async def delete_goal(gid: str) -> JSONResponse:
        return JSONResponse({"ok": _store().remove(gid)})
