"""自我改进 —— 把反复做的工作流"固化"成一个可复用 skill。

当某类任务反复出现(pattern_tracker 会提示),agent 可用 skill.scaffold 把这套做法
沉淀成 skills 目录下的一个新 skill:下次同类任务,调 skill.<name> 即可拿到这套
固定步骤/要点,不必每次从头摸索。

安全考量:生成的 impl.py 是**固定模板**,只回放你写入的"步骤说明文本",
不执行 agent 自由编写的任意代码——固化的是"做法 playbook",不是可执行逻辑。
新 skill 写到用户技能目录(默认 ~/.agents/skills/),不污染内置 skills/。
"""
from __future__ import annotations

import os
import re
from typing import Any

from capabilities.tools.base import Tool
from core.types import CapabilityResult, Risk

_IMPL_TEMPLATE = '''"""{name} —— 由自我改进固化的工作流 playbook(自动生成)。"""
from __future__ import annotations

from core.types import CapabilityResult

SCHEMA = {{"type": "object", "properties": {{}}}}

_STEPS = """{steps}"""


async def run(args: dict, ctx) -> CapabilityResult:
    return CapabilityResult(ok=True, output=_STEPS)
'''


def _user_skills_dir() -> str:
    d = os.environ.get("AGENT_USER_SKILLS_DIR", "~/.agents/skills")
    return os.path.expanduser(d)


def _safe_name(name: str) -> str:
    n = re.sub(r"[^a-zA-Z0-9_]+", "_", (name or "").strip().lower()).strip("_")
    return n[:40]


class SkillScaffold(Tool):
    name = "skill.scaffold"
    risk = Risk.WRITE  # 写入持久 skill 文件,Chat 需确认;Cowork 自动
    description = (
        "把一套反复使用的做法固化成一个新 skill(写到用户技能目录),"
        "下次同类任务调 skill.<name> 即可复用这套步骤。适合任务多次重复后沉淀经验。"
    )
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "skill 名(英文/下划线,如 weekly_report)"},
            "description": {"type": "string", "description": "一句话说明这个 skill 干什么"},
            "trigger": {"type": "string", "description": "触发关键词(空格分隔),帮助以后命中"},
            "steps": {"type": "string", "description": "固化的做法/步骤说明(会被原样回放)"},
        },
        "required": ["name", "description", "steps"],
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        name = _safe_name(str(args.get("name", "")))
        if not name:
            return CapabilityResult(ok=False, error="name 需含英文/数字")
        desc = str(args.get("description", "")).strip() or name
        trigger = str(args.get("trigger", "")).strip()
        steps = str(args.get("steps", "")).strip()
        if not steps:
            return CapabilityResult(ok=False, error="缺少 steps(要固化的做法)")
        # 防止把 \"\"\" 写进模板破坏语法
        steps_safe = steps.replace('"""', '\\"\\"\\"')

        base = _user_skills_dir()
        target = os.path.join(base, name)
        try:
            os.makedirs(target, exist_ok=True)
            md = (
                "---\n"
                f"name: {name}\n"
                f"description: {desc}\n"
                f"trigger: {trigger or name}\n"
                "risk: READ\n"
                "---\n\n"
                f"# {name}\n\n{desc}\n\n## 固化的做法\n\n{steps}\n"
            )
            with open(os.path.join(target, "SKILL.md"), "w", encoding="utf-8") as f:
                f.write(md)
            with open(os.path.join(target, "impl.py"), "w", encoding="utf-8") as f:
                f.write(_IMPL_TEMPLATE.format(name=name, steps=steps_safe))
        except Exception as e:
            return CapabilityResult(ok=False, error=str(e))

        # 标记该模式已固化,避免重复提示
        try:
            from memory.pattern_tracker import PatternTracker
            PatternTracker().mark_crystallized(desc)
        except Exception:
            pass
        return CapabilityResult(
            ok=True,
            output=f"已把做法固化为 skill「{name}」({target})。重启后可用 skill.{name} 复用。")
