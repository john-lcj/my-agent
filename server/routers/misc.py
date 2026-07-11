"""杂项端点：审计、连接器、命令、技能、治理统计、用量 (从 app.py 抽出，行为不变)。"""
from __future__ import annotations
import os

from fastapi import Request
from fastapi.responses import JSONResponse

from config import Config


def register_misc(app) -> None:

    @app.get("/api/improvements")
    async def list_improvements() -> JSONResponse:
        from core.improvement_governance import ImprovementStore
        return JSONResponse({"proposals": ImprovementStore(path=f"{Config.LOG_DIR}/improvements.jsonl").list()})

    @app.post("/api/improvements")
    async def create_improvement(request: Request) -> JSONResponse:
        from core.improvement_governance import ImprovementStore, propose
        body = await request.json()
        try:
            proposal = propose(
                title=str(body.get("title", "")), root_cause=str(body.get("root_cause", "")),
                expected_benefit=str(body.get("expected_benefit", "")), affected_paths=list(body.get("affected_paths") or []),
                risks=list(body.get("risks") or []), tests=list(body.get("tests") or []), rollback=str(body.get("rollback", "")),
            )
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        return JSONResponse({"ok": True, "proposal": ImprovementStore(path=f"{Config.LOG_DIR}/improvements.jsonl").add(proposal)})

    @app.post("/api/improvements/{proposal_id}/approve")
    async def approve_improvement(proposal_id: str, request: Request) -> JSONResponse:
        from core.improvement_governance import ImprovementStore
        body = await request.json()
        public_key = os.environ.get("CAPTAIN_RELEASE_PUBLIC_KEY", "").strip()
        if not public_key:
            return JSONResponse({"ok": False, "error": "release authority public key is not configured"}, status_code=503)
        try:
            proposal = ImprovementStore(path=f"{Config.LOG_DIR}/improvements.jsonl").approve(
                proposal_id, public_key, str(body.get("signature", "")),
            )
        except (KeyError, PermissionError) as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=403)
        return JSONResponse({"ok": True, "proposal": proposal})

    @app.post("/api/improvements/{proposal_id}/review")
    async def review_improvement(proposal_id: str, request: Request) -> JSONResponse:
        from core.improvement_governance import ImprovementStore
        body = await request.json()
        public_key = os.environ.get("CAPTAIN_REVIEW_PUBLIC_KEY", "").strip()
        if not public_key:
            return JSONResponse({"ok": False, "error": "independent reviewer public key is not configured"}, status_code=503)
        try:
            proposal = ImprovementStore(path=f"{Config.LOG_DIR}/improvements.jsonl").record_review(
                proposal_id, str(body.get("evidence_hash", "")), public_key, str(body.get("signature", "")),
            )
        except (KeyError, PermissionError) as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=403)
        return JSONResponse({"ok": True, "proposal": proposal})

    @app.post("/api/improvements/{proposal_id}/release-approve")
    async def approve_improvement_release(proposal_id: str, request: Request) -> JSONResponse:
        from core.improvement_governance import ImprovementStore
        body = await request.json(); public_key = os.environ.get("CAPTAIN_RELEASE_PUBLIC_KEY", "").strip()
        if not public_key:
            return JSONResponse({"ok": False, "error": "release authority public key is not configured"}, status_code=503)
        try:
            proposal = ImprovementStore(path=f"{Config.LOG_DIR}/improvements.jsonl").approve_release(
                proposal_id, str(body.get("evidence_hash", "")), public_key, str(body.get("signature", "")),
            )
        except (KeyError, PermissionError) as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=403)
        return JSONResponse({"ok": True, "proposal": proposal})

    @app.get("/api/trust")
    async def trust_dashboard() -> JSONResponse:
        """Inspectable, redacted view of P7 autonomy state."""
        from memory.goals_store import GoalsStore
        from memory.monitor_store import MonitorStore
        from memory.partnership_store import PartnershipStore
        from memory.suggestions_store import SuggestionsStore
        import server.app as _sa
        partnership = PartnershipStore(path=f"{Config.LOG_DIR}/partnership.json")
        from core.proactive_partnership import value_metrics
        missions = [
            {
                "id": mission.get("id", ""),
                "goal": str(mission.get("goal", ""))[:300],
                "status": mission.get("status", ""),
                "deadline": mission.get("deadline", ""),
                "blocked_reason": str(mission.get("blocked_reason", ""))[:300],
                "task_count": len(mission.get("tasks") or []),
                "updated_at": mission.get("updated_at", 0),
            }
            for mission in _sa._mission_store.list()
        ]
        return JSONResponse({
            "settings": partnership.settings(),
            "relationship": partnership.profile(),
            "goals": GoalsStore(path=f"{Config.LOG_DIR}/goals.json").graph(),
            "monitors": MonitorStore(path=f"{Config.LOG_DIR}/monitors.json").list(),
            # Mission results and user-supplied context may contain sensitive
            # material; trust status needs operational state, not raw content.
            "missions": missions,
            "commitments": partnership.commitments(),
            "pending_suggestions": SuggestionsStore(path=f"{Config.LOG_DIR}/suggestions.json").pending(),
            "value_metrics": value_metrics(partnership),
            "authority": "owner instructions only; external content cannot authorize side effects",
        })

    @app.post("/api/trust/settings")
    async def update_trust_settings(request: Request) -> JSONResponse:
        from memory.partnership_store import PartnershipStore
        body = await request.json()
        store = PartnershipStore(path=f"{Config.LOG_DIR}/partnership.json")
        return JSONResponse({"ok": True, "settings": store.update_settings(**body)})

    @app.post("/api/trust/profile")
    async def update_relationship_profile(request: Request) -> JSONResponse:
        from memory.partnership_store import PartnershipStore
        body = await request.json()
        store = PartnershipStore(path=f"{Config.LOG_DIR}/partnership.json")
        return JSONResponse({"ok": True, "profile": store.update_profile(**body)})

    @app.post("/api/commitments")
    async def add_commitment(request: Request) -> JSONResponse:
        from memory.partnership_store import PartnershipStore
        body = await request.json(); text = str(body.get("text", "")).strip()
        if not text:
            return JSONResponse({"ok": False, "error": "commitment text is required"}, status_code=400)
        store = PartnershipStore(path=f"{Config.LOG_DIR}/partnership.json")
        return JSONResponse({"ok": True, "commitment": store.add_commitment(text, due=str(body.get("due", "")), owner=str(body.get("owner", "owner")))})

    @app.post("/api/commitments/{cid}/resolve")
    async def resolve_commitment(cid: str) -> JSONResponse:
        from memory.partnership_store import PartnershipStore
        store = PartnershipStore(path=f"{Config.LOG_DIR}/partnership.json")
        return JSONResponse({"ok": store.resolve_commitment(cid)})

    @app.get("/api/audit")
    async def get_audit(limit: int = 100, capability: str = "", agent: str = "",
                        decision: str = "", ok: str = "") -> JSONResponse:
        from observability.audit import read_recent
        ok_val = None
        if ok.lower() in ("true", "1", "yes"):
            ok_val = True
        elif ok.lower() in ("false", "0", "no"):
            ok_val = False
        return JSONResponse({
            "records": read_recent(
                limit=min(max(limit, 1), 500),
                capability=capability, agent=agent, decision=decision, ok=ok_val,
            ),
        })

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
        return JSONResponse({"commands": list_slash_commands(resolve_skills_dirs())})

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

    @app.get("/api/briefing/preview")
    async def briefing_preview() -> JSONResponse:
        from core.briefing import build_daily_briefing_context, format_daily_briefing_email
        import server.app as _sa
        ctx = build_daily_briefing_context(
            log_dir=Config.LOG_DIR,
            longterm=_sa._longterm,
            mission_store=_sa._mission_store,
        )
        body = format_daily_briefing_email(
            log_dir=Config.LOG_DIR,
            mission_store=_sa._mission_store,
        )
        return JSONResponse({"context": ctx, "body": body})

    @app.get("/api/review/weekly")
    async def weekly_review_preview() -> JSONResponse:
        from core.proactive_partnership import weekly_review
        from memory.goals_store import GoalsStore
        from memory.partnership_store import PartnershipStore
        import server.app as _sa
        text = weekly_review(
            GoalsStore(path=f"{Config.LOG_DIR}/goals.json"),
            _sa._mission_store,
            PartnershipStore(path=f"{Config.LOG_DIR}/partnership.json"),
        )
        return JSONResponse({"review": text})

    @app.get("/api/usage")
    async def usage_stats(days: float = 30.0) -> JSONResponse:
        from server.usage_stats import load_usage
        trace_path = os.path.join(Config.LOG_DIR, "trace.jsonl")
        return JSONResponse(load_usage(trace_path, days=days))
