"""Mission 接口(/api/mission[s])—— 创建/查看/取消;创建后在后台顺序推进。

"如何在后台跑一个 mission"由 app.py 注入的 start_mission(mid) 决定(它用无人值守 agent
逐个执行子任务),本路由只管 CRUD,不依赖执行细节,便于解耦与测试。
"""
from __future__ import annotations

from typing import Callable

from fastapi import Request
from fastapi.responses import JSONResponse


def register_missions(app, store, start_mission: Callable[[str], None],
                      resume_mission: Callable[[str, str], None] | None = None) -> None:
    @app.get("/api/missions")
    async def list_missions() -> JSONResponse:
        return JSONResponse({"missions": store.list()})

    @app.get("/api/mission/{mid}")
    async def get_mission(mid: str) -> JSONResponse:
        m = store.get(mid)
        if m is None:
            return JSONResponse({"error": "mission 不存在"}, status_code=404)
        return JSONResponse(m)

    @app.post("/api/mission")
    async def create_mission(request: Request) -> JSONResponse:
        b = await request.json()
        goal = str(b.get("goal", "")).strip()
        if not goal:
            return JSONResponse({"ok": False, "error": "缺少 goal"}, status_code=400)
        try:
            level = int(b.get("attention_level", 2))
        except (TypeError, ValueError):
            level = 2
        m = store.create(goal, attention_level=level)
        if isinstance(b.get("tasks"), list) and b["tasks"]:
            store.set_tasks(m["id"], b["tasks"])
        try:
            start_mission(m["id"])    # 后台顺序推进(fire-and-forget)
        except Exception as e:
            return JSONResponse({"ok": True, "mission": store.get(m["id"]),
                                 "warn": f"已创建但未能启动后台执行:{e}"})
        return JSONResponse({"ok": True, "mission": store.get(m["id"])})

    @app.post("/api/mission/{mid}/resume")
    async def resume_mission_route(mid: str, request: Request) -> JSONResponse:
        m = store.get(mid)
        if m is None:
            return JSONResponse({"ok": False, "error": "mission 不存在"}, status_code=404)
        if m["status"] not in ("blocked", "waiting_user"):
            return JSONResponse({"ok": False, "error": "该任务当前不处于卡住/等待状态"}, status_code=400)
        try:
            b = await request.json()
        except Exception:
            b = {}
        info = str(b.get("info", "")).strip()
        if resume_mission is None:
            return JSONResponse({"ok": False, "error": "恢复未接线"}, status_code=503)
        resume_mission(mid, info)
        return JSONResponse({"ok": True})

    @app.post("/api/mission/{mid}/cancel")
    async def cancel_mission(mid: str) -> JSONResponse:
        m = store.get(mid)
        if m is None:
            return JSONResponse({"ok": False, "error": "mission 不存在"}, status_code=404)
        from core.mission import is_terminal
        if is_terminal(m["status"]):
            return JSONResponse({"ok": False, "error": "mission 已结束,无法取消"}, status_code=400)
        store.set_status(mid, "cancelled", reason="用户取消")
        return JSONResponse({"ok": True})
