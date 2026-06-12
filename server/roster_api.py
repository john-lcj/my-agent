"""Roster API —— 暴露 agents/roster/*.yaml 供 Web 圆桌与委托选择。"""
from __future__ import annotations

import os
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore


def list_roster_agents(roster_dir: str) -> list[dict[str, Any]]:
    if not os.path.isdir(roster_dir):
        return []
    agents: list[dict[str, Any]] = []
    for fname in sorted(os.listdir(roster_dir)):
        if not fname.endswith((".yaml", ".yml")):
            continue
        path = os.path.join(roster_dir, fname)
        data = _load_yaml(path)
        if not data:
            continue
        agent_id = data.get("id") or fname.rsplit(".", 1)[0]
        agents.append({
            "id": agent_id,
            "name": data.get("name", agent_id),
            "role": data.get("role", data.get("name", agent_id)),
            "description": data.get("description", ""),
            "system_prompt": data.get("system_prompt", ""),
            "model": data.get("llm") or data.get("model", "deepseek"),
            "capabilities": data.get("capabilities", []),
        })
    return agents


def _load_yaml(path: str) -> dict:
    if yaml is None:
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}
