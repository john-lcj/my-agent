"""斜杠命令清单 —— 供 Web / CLI 输入框补全。"""
from __future__ import annotations

import os
from typing import Any

from llm.model_registry import MODELS


def list_slash_commands(roster_dir: str, skills_dirs: str | list[str] = "skills") -> list[dict[str, Any]]:
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

    # 多 agent 专家命令已移除(单 agent 架构);只保留 /model 与 /skill。
    try:
        from skills.base import SkillRegistry
        reg = SkillRegistry(skills_dirs)
        reg.discover()
        for m in reg.available():
            items.append({
                "cmd": f"/{m.name}",
                "label": m.description or m.name,
                "hint": f"/{m.name} <参数>",
                "group": "Skill",
            })
    except Exception:
        pass

    return items
