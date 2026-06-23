"""评测框架深化回归 —— 新判据 + 分类汇总 + 基线对比 + LLM 质检员。"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evals.scoring import score_case, summarize, compare_baseline
from evals.judge import judge_quality


def test_min_length():
    ok, f = score_case("太短", [], {"min_length": 10})
    assert not ok and "太短" in f[0]
    assert score_case("这一段足够长足够长足够长", [], {"min_length": 5})[0]


def test_not_regex():
    # "用英文回答"→产出含中文应判挂
    ok, f = score_case("photosynthesis 是光合作用", [], {"not_regex": ["[\\u4e00-\\u9fff]"]})
    assert not ok and "不该匹配" in f[0]
    assert score_case("photosynthesis converts light", [], {"not_regex": ["[\\u4e00-\\u9fff]"]})[0]


def test_max_length():
    ok, f = score_case("这段话明显超过了十个字符的上限限制", [], {"max_length": 10})
    assert not ok and "超长" in f[0]
    assert score_case("短", [], {"max_length": 10})[0]


def test_max_and_min_together():
    # 字数窗口:既不能太短也不能太长
    assert score_case("刚刚好的一段", [], {"min_length": 3, "max_length": 20})[0]
    ok, _ = score_case("太长了太长了太长了太长了太长了太长了", [], {"min_length": 3, "max_length": 10})
    assert not ok


def test_not_capabilities():
    ok, f = score_case("巴黎", ["shell.run"], {"not_capabilities": ["shell.run"]})
    assert not ok and "不该调" in f[0]
    assert score_case("巴黎", ["web.search"], {"not_capabilities": ["shell.run"]})[0]


def test_capabilities_any():
    assert score_case("x", ["web.search"], {"capabilities_any": ["exa.search", "web.search"]})[0]
    ok, f = score_case("x", ["fs.read"], {"capabilities_any": ["exa.search", "web.search"]})
    assert not ok


def test_files_exist(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_WORKSPACE_ROOT", str(tmp_path))
    (tmp_path / "产物").mkdir()
    (tmp_path / "产物" / "r.md").write_text("x")
    assert score_case("见 产物/r.md", [], {"files_exist": ["r.md"]})[0]
    ok, f = score_case("见 产物/missing.md", [], {"files_exist": ["missing.md"]})
    assert not ok and "不存在" in f[0]


def test_file_contains():
    # 交付物在文件里 → 对照 files_text 而非对话回复
    ok, f = score_case("已保存,详见文件", [], {"file_contains": ["<section"]},
                       files_text='<section style="x">正文</section>')
    assert ok
    bad, fb = score_case("已保存", [], {"file_contains": ["<section"]}, files_text="纯文本无标签")
    assert not bad and "产出文件里缺少" in fb[0]


def test_summarize_by_category():
    s = summarize([
        {"passed": True, "category": "chat"},
        {"passed": False, "category": "chat"},
        {"passed": True, "category": "cowork"},
    ])
    assert s["total"] == 3 and s["passed"] == 2
    assert s["by_category"]["chat"] == {"total": 2, "passed": 1, "pass_rate": 0.5}
    assert s["by_category"]["cowork"]["pass_rate"] == 1.0


def test_compare_baseline():
    base = [{"name": "a", "passed": True}, {"name": "b", "passed": False},
            {"name": "c", "passed": True}]
    cur = [{"name": "a", "passed": False}, {"name": "b", "passed": True},
           {"name": "c", "passed": True}, {"name": "d", "passed": True}]
    diff = compare_baseline(cur, base)
    assert diff["regressed"] == ["a"]    # 原过现挂
    assert diff["fixed"] == ["b"]        # 原挂现过
    assert diff["new"] == ["d"]


def test_judge_with_fake_model(monkeypatch):
    class _Judge:
        name = "judge"
        async def next_step(self, messages, capabilities, emit_token=None):
            from core.types import Step
            return Step(text="8\n内容切题、表达通顺")
    import llm.factory as _f
    monkeypatch.setattr(_f, "build_role_llm", lambda *a, **k: _Judge())
    r = asyncio.run(judge_quality("写一段介绍", "一段还不错的内容", "是否切题通顺", 6))
    assert r and r["score"] == 8 and r["passed"] is True


def test_judge_below_threshold(monkeypatch):
    class _Judge:
        name = "judge"
        async def next_step(self, messages, capabilities, emit_token=None):
            from core.types import Step
            return Step(text="3\n跑题且空泛")
    import llm.factory as _f
    monkeypatch.setattr(_f, "build_role_llm", lambda *a, **k: _Judge())
    r = asyncio.run(judge_quality("写报告", "随便几个字", "是否达标", 6))
    assert r and r["score"] == 3 and r["passed"] is False
