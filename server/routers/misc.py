"""杂项端点：审计、连接器、命令、技能、治理统计、用量 (从 app.py 抽出，行为不变)。"""
from __future__ import annotations
import os

from fastapi.responses import JSONResponse

from config import Config


def register_misc(app, roster_dir) -> None:

    @app.get("/api/audit")
    async def get_audit(limit: int = 100) -> JSONResponse:
        from observability.audit import read_recent
        return JSONResponse({"records": read_recent(limit=min(max(limit, 1), 500))})

    @app.get("/api/connectors")
    async def list_connectors() -> JSONResponse:
        from capabilities.connector_loader import load_connector_specs
        out = []
        for s in load_connector_specs():
            out.append({
                "name":       s.get("name"),
                "label":      s.get("label", s.get("name")),
                "base_url":   s.get("base_url", ""),
                "secret_ref": (s.get("auth") or {}).get("secret_ref", ""),
                "auth_type":  (s.get("auth") or {}).get("type", "none"),
                "actions":    [{"name": a.get("name"), "method": a.get("method", "GET"),
                                "description": a.get("description", "")}
                               for a in s.get("actions", [])],
            })
        return JSONResponse({"connectors": out})

    @app.get("/api/commands")
    async def get_slash_commands() -> JSONResponse:
        from server.commands_api import list_slash_commands
        from skills.paths import resolve_skills_dirs
        return JSONResponse({"commands": list_slash_commands(roster_dir, resolve_skills_dirs())})

    @app.get("/api/skills")
    async def get_skills() -> JSONResponse:
        from skills.paths import build_skill_registry, resolve_skills_dirs
        reg = build_skill_registry()
        reg.discover()
        dirs = resolve_skills_dirs()
        project_root = os.path.abspath(dirs[0]) if dirs else ""
        items = []
        for m in reg.available():
            has_impl = os.path.isfile(os.path.join(m.path, "impl.py"))
            origin = "builtin" if os.path.abspath(m.source_root) == project_root else "user"
            items.append({
                "name":        m.name,
                "description": m.description,
                "cmd":         f"/{m.name}",
                "risk":        m.risk.name,
                "path":        m.path,
                "source_root": m.source_root,
                "has_impl":    has_impl,
                "origin":      origin,
            })
        return JSONResponse({"skills": items})

    @app.get("/api/governance/stats")
    async def governance_stats(days: float = 7.0) -> JSONResponse:
        from server.governance_stats import load_stats
        trace_path = os.path.join(Config.LOG_DIR, "trace.jsonl")
        return JSONResponse(load_stats(trace_path, days=days))

    @app.get("/api/usage")
    async def usage_stats(days: float = 30.0) -> JSONResponse:
        from server.usage_stats import load_usage
        trace_path = os.path.join(Config.LOG_DIR, "trace.jsonl")
        return JSONResponse(load_usage(trace_path, days=days))
