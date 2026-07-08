"""Skill scaffolding regressions."""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from capabilities.tools.skill_scaffold import SkillScaffold


def test_scaffold_writes_loadable_skill(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_USER_SKILLS_DIR", str(tmp_path))

    class Ctx:
        pass
    r = asyncio.run(SkillScaffold().invoke({
        "name": "Weekly Report!!",            # 含非法字符 → 应被规整
        "description": "Generate weekly reports with a fixed structure",
        "trigger": "周报 汇报",
        "steps": "1. 拉本周完成项\n2. 列下周计划\n3. 风险与求助",
    }, Ctx()))
    assert r.ok, r.error

    skill_dir = tmp_path / "weekly_report"
    manifest = skill_dir / "skill.json"
    assert manifest.is_file()
    assert json.loads(manifest.read_text(encoding="utf-8"))["name"] == "weekly_report"
    impl = skill_dir / "impl.py"
    assert impl.is_file()

    # impl.py 必须是合法、可导入、可运行的,返回固化步骤
    spec = importlib.util.spec_from_file_location("scaffolded_impl", str(impl))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    res = asyncio.run(mod.run({}, None))
    assert res.ok and "下周计划" in res.output


def test_rejects_empty_steps(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_USER_SKILLS_DIR", str(tmp_path))

    class Ctx:
        pass
    r = asyncio.run(SkillScaffold().invoke(
        {"name": "x", "description": "d", "steps": "  "}, Ctx()))
    assert not r.ok


def test_triple_quote_in_steps_does_not_break_impl(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_USER_SKILLS_DIR", str(tmp_path))

    class Ctx:
        pass
    r = asyncio.run(SkillScaffold().invoke({
        "name": "tricky", "description": "d",
        "steps": 'use """triple""" quotes safely',
    }, Ctx()))
    assert r.ok
    impl = tmp_path / "tricky" / "impl.py"
    spec = importlib.util.spec_from_file_location("tricky_impl", str(impl))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)   # 不应因三引号而语法错误
    res = asyncio.run(mod.run({}, None))
    assert res.ok
