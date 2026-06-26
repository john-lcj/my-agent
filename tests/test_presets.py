"""分人群预设 —— 预设块内容 + 注入系统提示词 + 默认通用。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.presets import preset_block
from core.prompts import build_system_prompt


def test_preset_blocks():
    assert "职场" in preset_block("office") and "docx_writer" in preset_block("office")
    assert "git" in preset_block("coder") and "push" in preset_block("coder")
    assert preset_block("general") == ""        # 通用不加块
    assert preset_block("乱写") == ""            # 未知=空


def test_preset_from_env(monkeypatch):
    monkeypatch.setenv("AGENT_PERSONA_PRESET", "coder")
    assert "程序员" in preset_block()
    monkeypatch.delenv("AGENT_PERSONA_PRESET", raising=False)
    assert preset_block() == ""


def test_preset_injected_into_system_prompt(monkeypatch):
    monkeypatch.setenv("AGENT_PERSONA_PRESET", "office")
    sp = build_system_prompt([], None)
    assert "职场工作者" in sp
    monkeypatch.setenv("AGENT_PERSONA_PRESET", "coder")
    sp2 = build_system_prompt([], None)
    assert "程序员" in sp2
    # 安全铁律仍在(预设不替换基础提示)
    assert "诚实" in sp2 or "做事铁律" in sp2
