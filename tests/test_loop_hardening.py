"""核心回路加固回归 —— 卡死检测 + 单步超时 + transcript 落盘。

用最小桩件直接驱动 AgentLoop,不依赖真实模型/网络。
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.loop import Agent
from core.bus import EventBus
from core.context import Context
from core.types import (CapabilityCall, CapabilityResult, Decision, Identity,
                        Risk, Step)
from governance.budget import BudgetGovernor


class _AllowPolicy:
    def review_detailed(self, call, identity, ctx):
        class R:
            decision = Decision.ALLOW
            reason = ""
            rule = "auto"
        return R()


class _Registry:
    """永远成功的工具表;记录被调用次数。"""
    def __init__(self, fail=False, hang=False):
        self.calls = 0
        self.fail = fail
        self.hang = hang

    def specs(self):
        return [{"name": "noop", "description": "", "schema": {}, "risk": 1}]

    def get(self, name):
        class C:
            risk = Risk.READ
        return C()

    async def invoke(self, name, args, ctx):
        self.calls += 1
        if self.hang:
            await asyncio.sleep(60)   # 模拟卡死
        if self.fail:
            return CapabilityResult(ok=False, error="boom")
        return CapabilityResult(ok=True, output="ok")


class _LoopingLLM:
    """永远返回同一个工具调用(模拟原地打转)。"""
    name = "fake"

    async def next_step(self, messages, capabilities, emit_token=None):
        return Step(call=CapabilityCall(name="noop", args={"x": 1}, intent="重复"))


class _VaryingFailLLM:
    """每次换不同参数调同一能力(模拟"换着花样试同一个用不了的能力")。"""
    name = "fake"

    def __init__(self):
        self.n = 0

    async def next_step(self, messages, capabilities, emit_token=None):
        self.n += 1
        return Step(call=CapabilityCall(name="noop", args={"x": self.n}, intent="换参数再试"))


async def _confirm(call, decision, reason=""):
    return True


def _loop(registry, **kw):
    return Agent(_LoopingLLM(), registry, _AllowPolicy(), EventBus(),
                 budget=BudgetGovernor(max_steps=100), **kw)


def test_stall_detection_stops_repeating(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_LOG_DIR", str(tmp_path))
    reg = _Registry()
    loop = _loop(reg)
    ctx = Context(identity=Identity(subject_id="u", agent_name="main", channel="web"))
    out = asyncio.run(loop.run("做点事", ctx, _confirm))
    assert "卡死" in out or "反复执行同一动作" in out
    # 不应把 100 步全烧光:卡死保护在第 5 次重复就收尾
    assert reg.calls <= 5
    # transcript 应落盘且记录了卡死
    tdir = tmp_path / "transcripts"
    files = list(tdir.glob("*.md")) if tdir.is_dir() else []
    assert files and "卡死" in files[0].read_text(encoding="utf-8")


def test_cap_fail_thrash_protection(tmp_path, monkeypatch):
    # 同一能力换着参数反复失败(签名各异,卡死检测抓不到)→ 失败追踪应在第4次收尾
    monkeypatch.setenv("AGENT_LOG_DIR", str(tmp_path))
    reg = _Registry(fail=True)
    loop = Agent(_VaryingFailLLM(), reg, _AllowPolicy(), EventBus(),
                 budget=BudgetGovernor(max_steps=100))
    ctx = Context(identity=Identity(subject_id="u", agent_name="main", channel="web"))
    out = asyncio.run(loop.run("生成一张图", ctx, _confirm))
    assert "反复失败" in out
    assert reg.calls <= loop._cap_fail_stop_at   # 没把 100 步烧光


def test_anti_sycophancy_injects_on_pressure():
    loop = _loop(_Registry())
    ctx = Context(identity=Identity(subject_id="u", agent_name="main", channel="web"))
    loop._inject_anti_sycophancy("珠峰是世界第二高峰,对吧?顺着我说", ctx)
    sys_msgs = [m.content for m in ctx.messages if str(getattr(m, "role", "")).endswith("SYSTEM")
                or getattr(m.role, "name", "") == "SYSTEM"]
    assert any(c.startswith("[抗谄媚]") for c in sys_msgs)


def test_anti_sycophancy_silent_when_neutral():
    loop = _loop(_Registry())
    ctx = Context(identity=Identity(subject_id="u", agent_name="main", channel="web"))
    before = len(ctx.messages)
    loop._inject_anti_sycophancy("帮我把这个 CSV 转成 JSON", ctx)
    # 中性问题不该注入,零开销
    assert all(not m.content.startswith("[抗谄媚]") for m in ctx.messages)
    assert len(ctx.messages) == before


def test_step_timeout_does_not_hang(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_LOG_DIR", str(tmp_path))
    reg = _Registry(hang=True)
    loop = _loop(reg)
    loop.step_timeout = 0.3   # 收紧超时,挂起的工具应被中断而非卡死整轮
    ctx = Context(identity=Identity(subject_id="u", agent_name="main", channel="web"))
    out = asyncio.run(asyncio.wait_for(loop.run("做点事", ctx, _confirm), timeout=10))
    # 超时后该步失败,模型继续重复→最终走卡死保护收尾,而不是永久挂起
    assert out  # 能正常返回(没卡死)
