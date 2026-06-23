"""交付校验门回归 —— 两层:确定性(存在/结构) + 语义质检(LLM)。"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.loop import Agent
from core.bus import EventBus
from core.types import Step


def _agent(llm=None):
    return Agent(llm=llm, registry=None, policy=None, bus=EventBus())


# ── 第一层:确定性 ──
def test_flags_missing_file(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", str(tmp_path))
    g = _agent()._completion_gate("写个报告", "报告已完成,见 产物/不存在的报告.md")
    assert g and "并不存在" in g


def test_passes_when_file_exists(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", str(tmp_path))
    (tmp_path / "产物").mkdir()
    (tmp_path / "产物" / "报告.md").write_text("这是一份足够长的报告内容，覆盖了任务要点。")
    assert _agent()._completion_gate("写报告", "已完成,见 产物/报告.md") == ""


def test_flags_empty_file(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", str(tmp_path))
    (tmp_path / "产物").mkdir()
    (tmp_path / "产物" / "data.json").write_text("[]")   # 2 字节,空
    g = _agent()._completion_gate("抓取数据", "已抓取并保存 产物/data.json")
    assert g and "几乎是空的" in g


def test_flags_wechat_plain_markdown(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", str(tmp_path))
    (tmp_path / "产物").mkdir()
    (tmp_path / "产物" / "tui.md").write_text("# 标题\n\n这是正文，没有任何 HTML。" * 5)
    g = _agent()._completion_gate("写一篇公众号推文", "公众号文章已完成,见 产物/tui.md")
    assert g and "纯 Markdown" in g


def test_wechat_html_passes(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", str(tmp_path))
    (tmp_path / "产物").mkdir()
    (tmp_path / "产物" / "tui.md").write_text('<section style="x"><p style="y">正文</p></section>')
    assert _agent()._completion_gate("写公众号推文", "见 产物/tui.md") == ""


# ── 第二层:语义质检 ──
class _JudgeLLM:
    name = "judge"

    def __init__(self, verdict):
        self.verdict = verdict

    async def next_step(self, messages, capabilities, emit_token=None):
        return Step(text=self.verdict)


def test_judge_flags_incomplete(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", str(tmp_path))
    (tmp_path / "产物").mkdir()
    (tmp_path / "产物" / "r.md").write_text("一些内容")
    a = _agent(llm=_JudgeLLM("缺少数据来源，且没有覆盖欧洲部分"))
    g = asyncio.run(a._content_judge("写一份带数据的欧洲报告", "见 产物/r.md"))
    assert g and "缺少数据来源" in g


def test_judge_ok_passes(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", str(tmp_path))
    (tmp_path / "产物").mkdir()
    (tmp_path / "产物" / "r.md").write_text("完整内容")
    a = _agent(llm=_JudgeLLM("OK"))
    assert asyncio.run(a._content_judge("写报告", "见 产物/r.md")) == ""


def test_judge_disabled_or_no_llm(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", str(tmp_path))
    (tmp_path / "产物").mkdir()
    (tmp_path / "产物" / "r.md").write_text("x")
    # 无 llm → 安静放行
    assert asyncio.run(_agent(llm=None)._content_judge("t", "见 产物/r.md")) == ""
    # 显式关闭 → 放行
    monkeypatch.setenv("AGENT_CONTENT_JUDGE", "0")
    a = _agent(llm=_JudgeLLM("有问题"))
    assert asyncio.run(a._content_judge("t", "见 产物/r.md")) == ""
