"""角色模型回归 —— judge/reflect 用独立(更会想的)模型,执行用主模型。"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm.factory import role_model_id, build_role_llm


def test_role_unset_means_main(monkeypatch):
    monkeypatch.delenv("AGENT_JUDGE_MODEL", raising=False)
    assert role_model_id("judge") == ""
    assert build_role_llm("judge") is None   # 回退主模型


def test_role_main_keyword(monkeypatch):
    monkeypatch.setenv("AGENT_JUDGE_MODEL", "main")
    assert role_model_id("judge") == ""


def test_role_set_resolves(monkeypatch):
    monkeypatch.setenv("AGENT_REFLECT_MODEL", "deepseek-v4-pro")
    assert role_model_id("reflect") == "deepseek-v4-pro"
    llm = build_role_llm("reflect")        # 构造不发网络,应得到一个 LLM 实例
    assert llm is not None and getattr(llm, "name", "") in ("deepseek", "fallback")


def test_judge_uses_main_when_unset(monkeypatch, tmp_path):
    # 未配 judge 模型时,_content_judge 应直接用主模型(测试里的假 LLM)
    monkeypatch.delenv("AGENT_JUDGE_MODEL", raising=False)
    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", str(tmp_path))
    (tmp_path / "产物").mkdir()
    (tmp_path / "产物" / "r.md").write_text("内容")

    from core.loop import Agent
    from core.bus import EventBus
    from core.types import Step

    class _Judge:
        name = "judge-fake"
        async def next_step(self, messages, capabilities, emit_token=None):
            return Step(text="缺少数据来源")

    a = Agent(llm=_Judge(), registry=None, policy=None, bus=EventBus())
    g = asyncio.run(a._content_judge("写带数据的报告", "见 产物/r.md"))
    assert "缺少数据来源" in g    # 用了主模型(假 LLM)的判词
