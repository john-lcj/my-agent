"""CLI 确认体验回归 —— 回车=是 / aa=全自动 / 高危仍二次确认。"""
from __future__ import annotations

import asyncio
import builtins
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from channels.cli import CLIChannel
from core.types import CapabilityCall, Decision


def _call(name="fs.write", **args):
    return CapabilityCall(name=name, args=args or {"path": "x.txt"})


def _confirm(ch, call, reason="", fake_input=""):
    builtins_input = builtins.input
    builtins.input = lambda *a, **k: fake_input
    try:
        return asyncio.run(ch.confirm(call, Decision.ASK, reason))
    finally:
        builtins.input = builtins_input


def test_enter_means_yes():
    ch = CLIChannel()
    assert _confirm(ch, _call(), fake_input="") is True


def test_n_means_no():
    ch = CLIChannel()
    assert _confirm(ch, _call(), fake_input="n") is False


def test_aa_enables_auto_for_session():
    ch = CLIChannel()
    # 第一次输入 aa 开启全自动并放行
    assert _confirm(ch, _call(), fake_input="aa") is True
    assert ch.auto_confirm_all is True
    # 之后非高危调用无需再问(即便输入是 n 也不会被读取)
    assert _confirm(ch, _call(), fake_input="n") is True


def test_high_risk_still_prompts_under_auto():
    ch = CLIChannel()
    ch.auto_confirm_all = True
    # 花钱类:即使全自动也要落到人工提示;这里 fake 回车=是
    assert _confirm(ch, _call(name="payment.charge"), reason="涉及花钱/支付,需你确认。", fake_input="") is True
    # 若人工答 n,则拒绝
    assert _confirm(ch, _call(name="payment.charge"), reason="涉及花钱/支付,需你确认。", fake_input="n") is False


def test_aa_cannot_enable_via_high_risk():
    ch = CLIChannel()
    # 在高危提示里输入 aa 不应开启全自动(防一键失控)
    _confirm(ch, _call(name="gui.control"), reason="控制电脑图形界面,需你确认。", fake_input="aa")
    assert ch.auto_confirm_all is False


def test_env_var_enables_auto():
    os.environ["AGENT_AUTO_CONFIRM"] = "1"
    try:
        ch = CLIChannel()
        assert ch.auto_confirm_all is True
        assert _confirm(ch, _call(), fake_input="n") is True  # 不读输入,自动放行
    finally:
        del os.environ["AGENT_AUTO_CONFIRM"]
