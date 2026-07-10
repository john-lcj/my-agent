"""Self-improvement tool for saving repeated workflows as reusable skills."""
from __future__ import annotations

import json
import os
import re
from typing import Any

from capabilities.tools.base import Tool
from core.types import CapabilityResult, Risk
from governance.workspace import resolve_path

_IMPL_TEMPLATE = '''"""{name} —— 由自我改进固化的工作流 playbook(自动生成)。"""
from __future__ import annotations

from core.types import CapabilityResult

SCHEMA = {{"type": "object", "properties": {{}}}}

_STEPS = """{steps}"""


async def run(args: dict, ctx) -> CapabilityResult:
    return CapabilityResult(ok=True, output=_STEPS)
'''


def _generated_skills_dir() -> tuple[str, str]:
    """Generated code is always a workspace artifact, never a home-directory write."""
    configured = os.environ.get("AGENT_GENERATED_SKILLS_DIR", "").strip()
    return resolve_path(configured or ".agent/skills")


def _safe_name(name: str) -> str:
    n = re.sub(r"[^a-zA-Z0-9_]+", "_", (name or "").strip().lower()).strip("_")
    return n[:40]


class SkillScaffold(Tool):
    name = "skill.scaffold"
    risk = Risk.WRITE
    description = (
        "Save a repeated workflow as a reusable user skill. The generated skill "
        "uses skill.json plus impl.py so it can sync without Markdown metadata."
    )
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Skill name in English or snake_case, such as weekly_report"},
            "description": {"type": "string", "description": "One-sentence explanation of what this skill does"},
            "trigger": {"type": "string", "description": "Space-separated trigger keywords for later matching"},
            "steps": {"type": "string", "description": "Captured workflow or steps, replayed verbatim"},
        },
        "required": ["name", "description", "steps"],
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        name = _safe_name(str(args.get("name", "")))
        if not name:
            return CapabilityResult(ok=False, error="name must contain letters or digits")
        desc = str(args.get("description", "")).strip() or name
        trigger = str(args.get("trigger", "")).strip()
        steps = str(args.get("steps", "")).strip()
        if not steps:
            return CapabilityResult(ok=False, error="steps is required")
        steps_safe = steps.replace('"""', '\\"\\"\\"')

        base, error = _generated_skills_dir()
        if error:
            return CapabilityResult(ok=False, error=error)
        target = os.path.join(base, name)
        try:
            os.makedirs(target, exist_ok=True)
            manifest = {
                "name": name,
                "description": desc,
                "trigger": trigger or name,
                "risk": "READ",
                "security_manifest": {
                    "data_scope": "workspace",
                    "side_effect": "none",
                    "reversible": True,
                    "authorization": "auto-read",
                    "timeout_seconds": 30,
                    "verification": "tool-result",
                    "source": "generated-workspace-skill",
                },
            }
            with open(os.path.join(target, "skill.json"), "w", encoding="utf-8") as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)
                f.write("\n")
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
            output=f"Saved workflow as skill `{name}` at {target}. Restart to use skill.{name}.")
