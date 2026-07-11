"""P7 deterministic reports and opportunity detection based on durable state."""
from __future__ import annotations

from memory.partnership_store import PartnershipStore


def detect_opportunities(goal_store, mission_store, partnership: PartnershipStore) -> list[dict]:
    if not partnership.settings().get("enabled", True):
        return []
    active = goal_store.active_texts()
    active_missions = {m.get("goal", "") for m in mission_store.list() if m.get("status") in {"created", "planning", "executing"}}
    return [{"kind": "goal_progress", "text": f"Advance goal: {goal}", "action": f"Review the next safe step for: {goal}"}
            for goal in active if not any(goal[:20] in mission for mission in active_missions)][:3]


def weekly_review(goal_store, mission_store, partnership: PartnershipStore) -> str:
    goals = goal_store.active_texts()
    missions = mission_store.list()
    completed = [m.get("goal", "") for m in missions if m.get("status") == "completed"]
    unfinished = [m.get("goal", "") for m in missions if m.get("status") in {"created", "planning", "executing", "blocked", "waiting_user"}]
    commitments = [c.get("text", "") for c in partnership.commitments("open")]
    return "\n".join([
        "Captain weekly review", "Completed: " + ("; ".join(completed[:8]) or "none"),
        "Unfinished: " + ("; ".join(unfinished[:8]) or "none"),
        "Open commitments: " + ("; ".join(commitments[:8]) or "none"),
        "Active goals: " + ("; ".join(goals[:8]) or "none"),
    ])


def value_metrics(partnership: PartnershipStore) -> dict[str, int]:
    events = partnership.events(days=30)
    accepted = sum(event.get("kind") == "suggestion_accepted" for event in events)
    rejected = sum(event.get("kind") == "suggestion_rejected" for event in events)
    completed = sum(row.get("status") == "done" for row in partnership.commitments())
    return {
        "accepted_suggestions": accepted,
        "rejected_suggestions": rejected,
        "completed_commitments": completed,
        "recorded_proactive_events": len(events),
    }
