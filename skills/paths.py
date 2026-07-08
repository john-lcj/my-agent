"""Resolve built-in, user, and optional extra skill directories."""
from __future__ import annotations

import os

from config import Config


def resolve_skills_dirs() -> list[str]:
    """Return skill roots in priority order; first discovered names win."""
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
    for part in extra.split(os.pathsep):
        part = part.strip()
        if part:
            _add(part)

    return dirs


def build_skill_registry():
    """Build a SkillRegistry from resolved skill directories."""
    from skills.base import SkillRegistry

    return SkillRegistry(resolve_skills_dirs())
