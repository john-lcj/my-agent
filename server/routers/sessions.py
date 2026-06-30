"""会话管理、分享、导出、回滚端点 (从 app.py 抽出，行为不变)。
注意：/api/feedback 保留在 app.py（测试需要 patch appmod._feedback_store）。
"""
from __future__ import annotations
import os

from fastapi import Request
from fastapi.responses import JSONResponse

from config import Config


def register_sessions(app, session_store) -> None:

    def _session_pairs(sid: str) -> list[dict]:
        try:
            msgs = session_store.load(sid)
        except Exception:
            return []
        out = []
        for m in msgs:
            role = getattr(getattr(m, "role", None), "value", "") or ""
            if role == "system":
                continue
            out.append({"role": role, "content": getattr(m, "content", "") or ""})
        return out

    def _session_markdown(sid: str, title: str = "") -> str:
        lines = [f"# {title or '对话'}\n"]
        for p in _session_pairs(sid):
            who = "你" if p["role"] == "user" else "Captain"
            lines.append(f"**{who}：**\n\n{p['content']}\n")
        return "\n".join(lines)

    @app.get("/api/sessions")
    async def list_sessions(project_id: str = "") -> JSONResponse:
        return JSONResponse({"sessions": session_store.list_sessions(project_id=project_id or None)})

    @app.get("/api/sessions/search")
    async def search_sessions(q: str = "") -> JSONResponse:
        return JSONResponse({"sessions": session_store.search_sessions(q)})

    @app.get("/api/sessions/{sid}/export.md")
    async def export_session_md(sid: str):
        from starlette.responses import Response as _Resp
        md = _session_markdown(sid)
        return _Resp(content=md, media_type="text/markdown; charset=utf-8",
                     headers={"Content-Disposition": f'attachment; filename="conversation-{sid[:8]}.md"'})

    @app.post("/api/share/conversation/{sid}")
    async def share_conversation(sid: str, request: Request) -> JSONResponse:
        from memory.share_store import ShareStore
        b = await request.json()
        pairs = _session_pairs(sid)
        if not pairs:
            return JSONResponse({"ok": False, "error": "该对话没有内容可分享"}, status_code=400)
        token = ShareStore(path=f"{Config.LOG_DIR}/shares.json").create(
            "conversation", b.get("title", "对话分享"), {"messages": pairs})
        return JSONResponse({"ok": True, "token": token, "url": f"/share/{token}"})

    @app.post("/api/share/artifact")
    async def share_artifact(request: Request) -> JSONResponse:
        from memory.share_store import ShareStore
        b = await request.json()
        path = str(b.get("path", "")).strip()
        ws = os.path.abspath(os.environ.get("AGENT_WORKSPACE_ROOT", "") or os.getcwd())
        full = os.path.abspath(path if os.path.isabs(path) else os.path.join(ws, path))
        if not (full == ws or full.startswith(ws + os.sep)) or not os.path.isfile(full):
            return JSONResponse({"ok": False, "error": "文件不存在或越出工作区"}, status_code=400)
        try:
            content = open(full, encoding="utf-8", errors="replace").read()
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
        token = ShareStore(path=f"{Config.LOG_DIR}/shares.json").create(
            "artifact", os.path.basename(full),
            {"name": os.path.basename(full), "content": content})
        return JSONResponse({"ok": True, "token": token, "url": f"/share/{token}"})

    @app.get("/share/{token}")
    async def view_share(token: str):
        from memory.share_store import ShareStore
        from starlette.responses import HTMLResponse as _HTML
        import html as _h
        rec = ShareStore(path=f"{Config.LOG_DIR}/shares.json").get(token)
        if rec is None:
            return _HTML("<h2>分享不存在或已过期</h2>", status_code=404)
        title = _h.escape(rec.get("title", "分享"))
        pl = rec.get("payload", {})
        if rec.get("kind") == "artifact":
            name = (pl.get("name") or "").lower()
            body = pl.get("content", "")
            if name.endswith((".html", ".htm")):
                inner = body
            else:
                inner = f'<pre style="white-space:pre-wrap">{_h.escape(body)}</pre>'
        else:
            parts = []
            for m in pl.get("messages", []):
                who = "你" if m["role"] == "user" else "Captain"
                parts.append(f'<div class="m {m["role"]}"><b>{who}</b>'
                              f'<div>{_h.escape(m["content"])}</div></div>')
            inner = "\n".join(parts)
        page = (
            "<!doctype html><meta charset='utf-8'>"
            f"<title>{title}</title>"
            "<style>body{max-width:760px;margin:24px auto;padding:0 16px;"
            "font-family:-apple-system,sans-serif;line-height:1.7;color:#222}"
            ".m{margin:14px 0;padding:12px 14px;border-radius:10px;background:#f6f7f9}"
            ".m.user{background:#eef3fb}.m b{color:#07689f;font-size:13px}"
            ".m div{white-space:pre-wrap;margin-top:4px}"
            "footer{margin-top:30px;color:#999;font-size:12px;text-align:center}</style>"
            f"<h2>{title}</h2>{inner}<footer>由 Captain 分享 · 只读快照</footer>")
        return _HTML(page)

    async def _rename_session(session_id: str, title: str) -> JSONResponse:
        if not session_store.update_title(session_id, title):
            return JSONResponse({"ok": False, "error": "会话不存在"}, status_code=404)
        return JSONResponse({"ok": True, "title": title})

    @app.patch("/api/sessions/{session_id}")
    async def rename_session(session_id: str, request: Request) -> JSONResponse:
        body = await request.json()
        return await _rename_session(session_id, str(body.get("title", "")).strip())

    @app.post("/api/sessions/{session_id}/rename")
    async def rename_session_post(session_id: str, request: Request) -> JSONResponse:
        body = await request.json()
        return await _rename_session(session_id, str(body.get("title", "")).strip())

    @app.delete("/api/sessions/{session_id}")
    async def delete_session(session_id: str) -> JSONResponse:
        session_store.delete_session(session_id)
        return JSONResponse({"ok": True})

    @app.post("/api/rollback")
    async def rollback_last(request: Request) -> JSONResponse:
        body = await request.json()
        trace_id = body.get("trace_id", "")
        from observability.rollback import RollbackManager
        rb = RollbackManager(snapshot_dir=f"{Config.LOG_DIR}/snapshots")
        if not trace_id:
            return JSONResponse({"ok": False, "error": "缺少 trace_id"}, status_code=400)
        notes = rb.rollback(trace_id)
        return JSONResponse({"ok": True, "notes": notes})
