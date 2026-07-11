from __future__ import annotations

import json

from memory.goals_store import GoalsStore


def test_p7_goal_graph_migrates_legacy_goals_and_keeps_active_texts(tmp_path):
    path = tmp_path / "goals.json"
    path.write_text(json.dumps([{"id": "old", "text": "Launch Captain", "kind": "goal", "enabled": True}]), encoding="utf-8")
    store = GoalsStore(path=str(path))
    assert store.active_texts() == ["Launch Captain"]
    project = store.create_node("Captain P7", kind="project", owner="owner", deadline="2026-08-01")
    milestone = store.create_node("Ship goal graph", kind="milestone")
    edge = store.link(project["id"], milestone["id"], "contains")
    assert edge["relation"] == "contains"
    assert len(store.graph()["nodes"]) == 3
    assert store.remove(project["id"])
    assert store.graph()["edges"] == []
