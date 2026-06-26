"""主动建议接口(/api/suggestions)—— 从 app.py 抽出,行为不变。

accept 接受后,若建议带可执行指令,需把它丢进后台任务队列——这一步通过 enqueue
回调注入(由 app.py 传 _daemon_enqueue 进来),从而不引入对 app.py 的反向依赖。
"""
from __future__ import annotations

from typing import Callable

from fastapi.responses import JSONResponse

from config import Config


def _store():
    from memory.suggestions_store import SuggestionsStore
    return SuggestionsStore(path=f"{Config.LOG_DIR}/suggestions.json")


def register_suggestions(app, enqueue: Callable[..., str]) -> None:
    @app.get("/api/suggestions")
    async def list_suggestions() -> JSONResponse:
        return JSONResponse({"suggestions": _store().pending()})

    @app.post("/api/suggestions/{sid}/accept")
    async def accept_suggestion(sid: str) -> JSONResponse:
        rec = _store().set_status(sid, "accepted")
        if rec is None:
            return JSONResponse({"ok": False, "error": "建议不存在"}, status_code=404)
        tid = ""
        if rec.get("action"):   # 有可执行指令 → 进后台任务队列去做
            tid = enqueue(rec["action"], source="suggestion", mode="coworker")
        return JSONResponse({"ok": True, "task_id": tid})

    @app.post("/api/suggestions/{sid}/dismiss")
    async def dismiss_suggestion(sid: str) -> JSONResponse:
        ok = _store().set_status(sid, "dismissed") is not None
        return JSONResponse({"ok": ok})
