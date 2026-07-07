"""专注写作端点 (从 app.py 抽出，行为不变)。"""
from __future__ import annotations
import os

from fastapi import Request
from fastapi.responses import JSONResponse


def register_writing(app) -> None:
    @app.post("/api/writing/assist")
    async def writing_assist(request: Request) -> JSONResponse:
        b = await request.json()
        text = str(b.get("text", ""))
        instruction = str(b.get("instruction", "")).strip()
        if not instruction:
            return JSONResponse({"ok": False, "error": "缺少指令"}, status_code=400)
        from llm.factory import build_llm
        from core.types import Message, Role
        sys_p = ("你是中文写作助手。严格按用户指令处理给定文本,**只返回处理后的Body text本身**——"
                 "不要任何解释、前后缀、引号,也不要『以下是…』之类的话。"
                 "若是续写类指令,只返回新增的后续内容(不重复原文)。")
        user_p = f"指令:{instruction}\n\n文本:\n{text or '(空)'}"
        try:
            llm = build_llm()
            step = await llm.next_step(
                [Message(role=Role.SYSTEM, content=sys_p),
                 Message(role=Role.USER, content=user_p)], [], None)
            out = (getattr(step, "text", "") or "").strip()
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)[:200]}, status_code=502)
        return JSONResponse({"ok": True, "text": out})

    @app.post("/api/writing/save")
    async def writing_save(request: Request) -> JSONResponse:
        b = await request.json()
        title = (str(b.get("title", "")).strip() or "未命名稿").replace("/", "_")[:60]
        if not title.lower().endswith((".md", ".txt")):
            title += ".md"
        content = str(b.get("content", ""))
        ws = os.environ.get("AGENT_WORKSPACE_ROOT", "").strip() or os.getcwd()
        d = os.path.join(ws, "产物")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, title)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
        return JSONResponse({"ok": True, "path": os.path.relpath(path, ws)})
