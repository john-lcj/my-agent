"""斜杠命令清单 —— 供 Web / CLI 输入框补全。"""
from __future__ import annotations

import os
from typing import Any

from llm.model_registry import MODELS


def list_slash_commands(skills_dirs: str | list[str] = "skills") -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    items.extend([
        {"cmd": "/model", "label": "列出可选大模型", "hint": "/model", "group": "系统"},
        {"cmd": "/experts", "label": "列出执行专家", "hint": "/experts", "group": "系统"},
        {"cmd": "/skills", "label": "列出 Skill 插件", "hint": "/skills", "group": "系统"},
        {"cmd": "/rollback", "label": "撤销上一任务文件改动", "hint": "/rollback", "group": "系统"},
    ])

    for m in MODELS:
        items.append({
            "cmd": f"/model {m.id}",
            "label": m.label,
            "hint": f"/model {m.id}",
            "group": "模型",
        })

    # Skill 命令：两种格式都注册，保证自动补全和直接输入都能工作。
    # - /skill <name> <args>：标准格式，走 parse_slash_command 的 "skill" 分支
    # - /<name> <args>：快捷格式，走 "name in skills" 分支（支持 Unicode 名称）
    try:
        from skills.base import SkillRegistry
        reg = SkillRegistry(skills_dirs)
        reg.discover()
        for m in reg.available():
            desc = m.description or m.name
            # 快捷格式（优先展示）
            items.append({
                "cmd": f"/skill {m.name}",
                "label": desc,
                "hint": f"/skill {m.name} <参数>",
                "group": "Skill",
            })
    except Exception:
        pass

    return items
