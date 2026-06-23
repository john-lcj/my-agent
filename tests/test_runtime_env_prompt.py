"""运行环境硬说明 + 待办清单引导必须进系统 prompt(单 agent 架构)。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_env_block_in_system_prompt():
    from core.prompts import build_system_prompt, runtime_env_block
    blk = runtime_env_block()
    assert "python3" in blk and "cd" in blk and "工作目录" in blk
    sp = build_system_prompt([{"name": "shell.run"}, {"name": "fs.write"}])
    assert "运行环境" in sp and "python3" in sp


def test_plan_guidance_in_system_prompt():
    from core.prompts import build_system_prompt
    sp = build_system_prompt([{"name": "plan.update"}, {"name": "fs.write"}])
    assert "待办清单" in sp and "plan.update" in sp
    # 没有 plan 能力时不应注入待办引导
    sp2 = build_system_prompt([{"name": "fs.write"}])
    assert "plan.update" not in sp2
