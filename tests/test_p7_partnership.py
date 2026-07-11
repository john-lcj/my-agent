from __future__ import annotations

from core.proactive_partnership import detect_opportunities, value_metrics, weekly_review
from memory.goals_store import GoalsStore
from memory.mission_store import MissionStore
from memory.partnership_store import PartnershipStore
from memory.suggestions_store import SuggestionsStore


def test_p7_partnership_controls_commitments_opportunities_and_review(tmp_path):
    goals = GoalsStore(path=str(tmp_path / "goals.json"))
    goals.add("Ship Captain P7", "goal")
    missions = MissionStore(db_path=str(tmp_path / "missions.db"))
    partnership = PartnershipStore(path=str(tmp_path / "partnership.json"))
    commitment = partnership.add_commitment("Review P7 status", due="2026-07-12")
    assert partnership.resolve_commitment(commitment["id"])
    assert detect_opportunities(goals, missions, partnership)
    partnership.update_settings(enabled=False)
    assert detect_opportunities(goals, missions, partnership) == []
    partnership.update_settings(enabled=True, interruption_budget=1)
    partnership.update_profile(detail="concise", intervention="ask-first")
    assert partnership.profile()["intervention"] == "ask-first"
    partnership.record("suggestion_accepted", "Advance P7")
    assert value_metrics(partnership)["accepted_suggestions"] == 1
    assert "Ship Captain P7" in weekly_review(goals, missions, partnership)


def test_p7_suggestions_expire_and_deduplicate_by_action(tmp_path):
    store = SuggestionsStore(path=str(tmp_path / "suggestions.json"))
    first = store.add("Review goal", action="open goal graph")
    assert store.add("Review goal", action="open goal graph")["id"] == first["id"]
    first["expires_at"] = 0
    store._write([first])
    assert store.pending() == []
    assert store.list()[0]["status"] == "expired"
