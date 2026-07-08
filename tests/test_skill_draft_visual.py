"""Skill drafts and visual QA."""
from __future__ import annotations

import os
import json

from core.visual_qa import check_artifact_layout
from memory.skill_drafter import confirm_draft, normalize_description, save_draft
from skills.base import SkillRegistry


def test_normalize_description_is_short_english():
    d = normalize_description("Reusable workflow distilled from repeated tasks")
    assert d == "Reusable workflow distilled from repeated tasks"
    assert len(d) <= 96


def test_confirm_draft_writes_skill(tmp_path):
    log_dir = str(tmp_path / "logs")
    skills = str(tmp_path / "skills")
    os.makedirs(skills)
    item = save_draft(log_dir, "test_skill", "Reusable file organization workflow", "organize files", "body")
    out = confirm_draft(log_dir, item["id"], skills_root=skills)
    assert out["status"] == "confirmed"
    manifest = os.path.join(skills, "test_skill", "skill.json")
    assert os.path.isfile(manifest)
    with open(manifest, encoding="utf-8") as f:
        assert json.load(f)["name"] == "test_skill"


def test_registry_discovers_impl_only_builtin_skills():
    reg = SkillRegistry("skills")
    reg.discover()
    names = {m.name for m in reg.available()}
    assert "csv_stats" in names
    assert "text_stats" in names


def test_visual_detects_empty_buttons(tmp_path):
    p = tmp_path / "bad.html"
    p.write_text("<html><button></button><button></button></html>", encoding="utf-8")
    r = check_artifact_layout(str(p))
    assert not r.ok
