"""项目空间 + 会话工作台端点 (从 app.py 抽出，行为不变)。"""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse


def register_projects(app, project_store, session_store) -> None:

    @app.get("/api/projects")
    async def list_projects() -> JSONResponse:
        return JSONResponse({"projects": project_store.list()})

    @app.post("/api/projects")
    async def create_project(request: Request) -> JSONResponse:
        b = await request.json()
        proj = project_store.create(
            name=b.get("name", ""), instructions=b.get("instructions", ""),
            knowledge=b.get("knowledge") or [], workspace=b.get("workspace", ""))
        return JSONResponse({"ok": True, "project": proj})

    @app.patch("/api/projects/{pid}")
    async def update_project(pid: str, request: Request) -> JSONResponse:
        b = await request.json()
        proj = project_store.update(pid, name=b.get("name"),
                                    instructions=b.get("instructions"),
                                    knowledge=b.get("knowledge"))
        if proj is None:
            return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)
        return JSONResponse({"ok": True, "project": proj})

    @app.delete("/api/projects/{pid}")
    async def delete_project(pid: str) -> JSONResponse:
        return JSONResponse({"ok": project_store.delete(pid)})

    @app.post("/api/sessions/{sid}/project")
    async def assign_session_project(sid: str, request: Request) -> JSONResponse:
        b = await request.json()
        ok = session_store.set_project(sid, b.get("project_id") or None)
        return JSONResponse({"ok": ok})

    @app.get("/api/sessions/{sid}/workbench")
    async def get_workbench(sid: str) -> JSONResponse:
        meta = session_store.get_meta(sid)
        return JSONResponse({"workspace_dir": meta.get("workspace_dir", ""),
                             "artifacts": meta.get("artifacts", []),
                             "plan": meta.get("plan", [])})

    @app.post("/api/sessions/{sid}/workbench")
    async def save_workbench(sid: str, request: Request) -> JSONResponse:
        b = await request.json()
        patch = {}
        if "workspace_dir" in b:
            patch["workspace_dir"] = str(b.get("workspace_dir") or "")
        if isinstance(b.get("artifacts"), list):
            cur = session_store.get_meta(sid).get("artifacts", [])
            merged = list(cur)
            for a in b["artifacts"]:
                a = str(a)
                if a and a not in merged:
                    merged.append(a)
            patch["artifacts"] = merged[-200:]
        if isinstance(b.get("plan"), list):
            patch["plan"] = b["plan"][:200]
        meta = session_store.merge_meta(sid, patch)
        return JSONResponse({"ok": True, "workspace_dir": meta.get("workspace_dir", ""),
                             "artifacts": meta.get("artifacts", []),
                             "plan": meta.get("plan", [])})
