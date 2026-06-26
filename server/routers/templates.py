"""提示词/模板库接口(/api/templates)—— 从 app.py 抽出,行为不变。"""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse


def register_templates(app, template_store) -> None:
    @app.get("/api/templates")
    async def list_templates() -> JSONResponse:
        return JSONResponse({"templates": template_store.list()})

    @app.post("/api/templates")
    async def save_template(request: Request) -> JSONResponse:
        b = await request.json()
        title = str(b.get("title", "")).strip()
        content = str(b.get("content", "")).strip()
        if not (title or content):
            return JSONResponse({"ok": False, "error": "标题和内容不能都为空"}, status_code=400)
        row = template_store.save(title=title, content=content,
                                  category=str(b.get("category", "")), tid=b.get("id"))
        return JSONResponse({"ok": True, "template": row})

    @app.delete("/api/templates/{tid}")
    async def delete_template(tid: str) -> JSONResponse:
        return JSONResponse({"ok": template_store.delete(tid)})
