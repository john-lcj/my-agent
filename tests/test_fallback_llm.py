"""失败回退 LLM 回归 —— 主模型失败自动切备用,全失败才抛。"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm.fallback import FallbackLLM
from core.types import Step


class FakeLLM:
    def __init__(self, name, fail=False):
        self.name = name
        self.fail = fail
        self.calls = 0

    async def next_step(self, messages, capabilities, emit_token=None):
        self.calls += 1
        if self.fail:
            raise RuntimeError(f"{self.name} 挂了")
        return Step(text=f"ok:{self.name}")


def test_primary_ok_backup_untouched():
    p, b = FakeLLM("p"), FakeLLM("b")
    s = asyncio.run(FallbackLLM(p, [b]).next_step([], []))
    assert s.text == "ok:p" and b.calls == 0


def test_falls_through_to_working_backup():
    p, b1, b2 = FakeLLM("p", fail=True), FakeLLM("b1", fail=True), FakeLLM("b2")
    s = asyncio.run(FallbackLLM(p, [b1, b2]).next_step([], []))
    assert s.text == "ok:b2" and p.calls == 1 and b1.calls == 1 and b2.calls == 1


def test_all_fail_raises_last():
    p, b = FakeLLM("p", fail=True), FakeLLM("b", fail=True)
    try:
        asyncio.run(FallbackLLM(p, [b]).next_step([], []))
        assert False, "应抛异常"
    except RuntimeError as e:
        assert "挂了" in str(e)


def test_factory_no_fallback_when_unset(monkeypatch):
    monkeypatch.setenv("AGENT_LLM_PROVIDER", "mock")
    monkeypatch.delenv("AGENT_FALLBACK_MODELS", raising=False)
    from llm.factory import build_llm
    llm = build_llm(model="mock") if False else build_llm()
    # 未配置回退 → 不应被 FallbackLLM 包裹
    assert llm.__class__.__name__ != "FallbackLLM"
