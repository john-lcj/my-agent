"""斜杠命令解析 —— 专家、skill、模型切换。"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal, Optional

from llm.model_registry import format_models_help, normalize_model_id

_CMD = re.compile(r"^/([a-zA-Z][\w-]*)(?:\s+(.*))?$", re.S)

SlashKind = Literal[
    "main",
    "list_experts",
    "invoke_expert",
    "list_skills",
    "invoke_skill",
    "list_models",
    "set_model",
    "unknown",
]


@dataclass
class SlashCommand:
    kind: SlashKind
    target: str = ""
    task: str = ""


ExpertCommand = SlashCommand


def parse_skill_args(skill_name: str, rest: str) -> dict:
    raw = (rest or "").strip()
    if not raw:
        return {}
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    return {"text": raw, "input": raw}


def parse_slash_command(
    text: str,
    expert_names: set[str],
    skill_names: set[str] | None = None,
) -> SlashCommand:
    raw = (text or "").strip()
    skills = skill_names or set()
    if not raw.startswith("/"):
        return SlashCommand(kind="main", task=raw)

    m = _CMD.match(raw)
    if not m:
        return SlashCommand(kind="main", task=raw)

    name, rest = m.group(1), (m.group(2) or "").strip()
    low = name.lower()

    if low in ("experts", "expert"):
        return SlashCommand(kind="list_experts")

    if low in ("skills", "skill-list"):
        return SlashCommand(kind="list_skills")

    if low == "skill":
        if not rest:
            return SlashCommand(kind="list_skills")
        parts = rest.split(None, 1)
        skill = parts[0]
        task = parts[1] if len(parts) > 1 else ""
        if skill in skills:
            return SlashCommand(kind="invoke_skill", target=skill, task=task)
        return SlashCommand(kind="unknown", target=skill)

    if low in ("model", "models", "provider", "providers"):
        if not rest or rest.lower() in ("list", "ls", "?"):
            return SlashCommand(kind="list_models")
        token = rest.split()[0].lower()
        mid = normalize_model_id(token)
        if mid:
            return SlashCommand(kind="set_model", target=mid)
        return SlashCommand(kind="unknown", target=token)

    if name in expert_names:
        task = rest or "请根据你的专长完成主人刚才的意图。"
        return SlashCommand(kind="invoke_expert", target=name, task=task)

    if name in skills:
        return SlashCommand(kind="invoke_skill", target=name, task=rest)

    return SlashCommand(kind="unknown", target=name)


def parse_expert_command(text: str, expert_names: set[str]) -> SlashCommand:
    return parse_slash_command(text, expert_names)


def format_experts_help(workers: list) -> str:
    lines = [
        "执行专家(仅显式调用;默认由 Captain 自己完成):",
        "  /experts              列出本帮助",
        "",
    ]
    for w in workers:
        role = getattr(w, "role", None) or getattr(w, "name", "?")
        desc = getattr(w, "description", None) or ""
        lines.append(f"  /{w.name} <任务>   {role}")
        if desc:
            lines.append(f"      {desc.strip()[:80]}")
    lines += [
        "",
        "示例: /code_agent 运行 pytest",
        "不带 / 的消息由 Captain 理解目标后自行拆解并执行。",
    ]
    return "\n".join(lines)


def format_skills_help(manifests: list) -> str:
    lines = [
        f"Skill 插件 · 共 {len(manifests)} 个(显式调用):",
        "  /skills               列出本帮助",
        "  /skill <名> <参数>    调用指定 skill",
        "",
    ]
    # 命令列左对齐,描述列对齐,读起来更整齐。
    width = max((len(m.name) for m in manifests), default=0) + 1
    for m in manifests:
        lines.append(f"  /{m.name.ljust(width)} {m.description or m.name}")
    lines += ["", "示例: /text_stats 你好世界"]
    return "\n".join(lines)
