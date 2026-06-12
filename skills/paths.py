"""Skill 目录解析 —— 内置 skills/ + 用户 ~/.agents/skills/ + 可选扩展目录。"""
from __future__ import annotations

import os

from config import Config


def resolve_skills_dirs() -> list[str]:
    """返回按优先级排序的 skill 根目录(先发现者优先,同名不覆盖)。"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dirs: list[str] = []

    def _add(path: str) -> None:
        path = os.path.abspath(os.path.expanduser(path))
        if os.path.isdir(path) and path not in dirs:
            dirs.append(path)

    _add(os.path.join(root, "skills"))

    user = os.environ.get("AGENT_USER_SKILLS_DIR", "~/.agents/skills")
    _add(user)

    extra = os.environ.get("AGENT_SKILLS_DIRS", "")
    for part in extra.split(":"):
        part = part.strip()
        if part:
            _add(part)

    return dirs


def build_skill_registry():
    """按 resolve_skills_dirs 构建 SkillRegistry。"""
    from skills.base import SkillRegistry

    return SkillRegistry(resolve_skills_dirs())
