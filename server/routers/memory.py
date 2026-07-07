"""长期记忆 CRUD API —— 全 kind 查看/删除 + skill 草稿。"""
from __future__ import annotations

import json

from fastapi import Request
from fastapi.responses import JSONResponse

from config import Config


def register_memory(app, longterm) -> None:

    @app.get("/api/memory")
    async def list_memory(kind: str = "", q: str = "", limit: int = 100) -> JSONResponse:
        k = (kind or "").strip() or None
        rows = longterm.list_all(kind=k, limit=min(max(limit, 1), 500))
        query = (q or "").strip().lower()
        if query:
            rows = [r for r in rows if query in (r.get("content") or "").lower()]
        return JSONResponse({"items": rows})

    @app.put("/api/memory/{row_id}")
    async def update_memory_row(row_id: int, request: Request) -> JSONResponse:
        body = await request.json()
        content = str(body.get("content") or "").strip()
        if not content:
            return JSONResponse({"ok": False, "error": "content 不能为空"}, status_code=400)
        fn = getattr(longterm, "update_by_id", None)
        if fn is None:
            return JSONResponse({"ok": False, "error": "不支持编辑"}, status_code=501)
        ok = bool(fn(int(row_id), content))
        return JSONResponse({"ok": ok})

    @app.delete("/api/memory/{row_id}")
    async def delete_memory_row(row_id: int) -> JSONResponse:
        fn = getattr(longterm, "delete_by_id", None)
        if fn is None:
            fn = getattr(getattr(longterm, "_kw", None), "delete_by_id", None)
        if fn is None:
            return JSONResponse({"ok": False, "error": "不支持删除"}, status_code=501)
        ok = bool(fn(int(row_id)))
        return JSONResponse({"ok": ok})

    @app.get("/api/memory/export")
    async def export_memory(kind: str = "") -> JSONResponse:
        k = (kind or "").strip() or None
        rows = longterm.list_all(kind=k, limit=500)
        return JSONResponse({"exported_at": Config.LOG_DIR, "items": rows})

    @app.get("/api/memory/skill-drafts")
    async def list_skill_drafts() -> JSONResponse:
        from memory.skill_drafter import list_drafts
        return JSONResponse({"drafts": list_drafts(Config.LOG_DIR)})

    @app.post("/api/memory/skill-drafts/{draft_id}/confirm")
    async def confirm_skill_draft(draft_id: str) -> JSONResponse:
        from memory.skill_drafter import confirm_draft
        try:
            item = confirm_draft(Config.LOG_DIR, draft_id)
            return JSONResponse({"ok": True, "draft": item})
        except KeyError:
            return JSONResponse({"ok": False, "error": "草稿不存在"}, status_code=404)
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)[:200]}, status_code=500)

    @app.delete("/api/memory/skill-drafts/{draft_id}")
    async def dismiss_skill_draft(draft_id: str) -> JSONResponse:
        from memory.skill_drafter import dismiss_draft
        ok = dismiss_draft(Config.LOG_DIR, draft_id)
        return JSONResponse({"ok": ok})

    @app.get("/api/governance/overview")
    async def governance_overview() -> JSONResponse:
        return JSONResponse({
            "workspace_root": Config.LOG_DIR,
            "policy_file": "policy.yaml",
            "notes": [
                "WRITE 风险 skill 须在 confirm.capabilities 中声明",
                "fs.* 受 AGENT_WORKSPACE_ROOT 约束",
                "外发邮件受 EMAIL_ALLOWED_RECIPIENTS 白名单约束",
            ],
        })

    @app.get("/api/governance/policy")
    async def governance_policy() -> JSONResponse:
        from governance.policy_summary import load_policy_summary
        return JSONResponse(load_policy_summary())
