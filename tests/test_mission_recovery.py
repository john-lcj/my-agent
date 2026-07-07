"""Mission 进程恢复与工作流模板。"""
from __future__ import annotations

from core.workflow_templates import WORKFLOW_TEMPLATES, seed_workflow_templates
from memory.mission_store import MissionStore, MissionStatus
from memory.template_store import TemplateStore


def test_seed_workflow_templates(tmp_path):
    ts = TemplateStore(db_path=str(tmp_path / "t.db"))
    n = seed_workflow_templates(ts)
    assert n == len(WORKFLOW_TEMPLATES)
    assert seed_workflow_templates(ts) == 0
    titles = {t["title"] for t in ts.list()}
    assert "文档交付" in titles


def test_executing_missions_listable(tmp_path):
    store = MissionStore(db_path=str(tmp_path / "m.db"))
    m = store.create(goal="续跑")
    store.set_status(m["id"], "planning")
    store.set_status(m["id"], MissionStatus.EXECUTING.value)
    rows = store.list(status="executing")
    assert len(rows) == 1
    assert rows[0]["id"] == m["id"]
