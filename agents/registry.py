"""Agent 注册表 —— 按名字查找可被委托/路由的 agent。

两种注册方式:
  1. register(agent)       手动注册已构建的 agent 对象
  2. load_from_roster()    扫描 roster 目录,用 WorkerFactory 自动构建并注册

多用户/多会话场景:每个会话可以有自己的注册表快照(按最小权限原则
只让当前 agent 看到它被授权委托的目标)。
"""
from __future__ import annotations

import sys
from typing import Optional


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, object] = {}

    def register(self, agent) -> None:
        self._agents[agent.name] = agent

    def get(self, name: str) -> Optional[object]:
        return self._agents.get(name)

    def names(self) -> list[str]:
        return list(self._agents.keys())

    def all(self) -> list:
        return list(self._agents.values())

    def __contains__(self, name: str) -> bool:
        return name in self._agents

    def load_from_roster(self, roster_dir: str, factory) -> int:
        """从 roster 目录自动发现、构建并注册所有 agent。返回注册数量。"""
        from agents.spec import load_specs_from_roster
        specs = load_specs_from_roster(roster_dir)
        count = 0
        for spec in specs:
            try:
                worker = factory.build(spec)
                self.register(worker)
                print(f"[registry] 注册 agent: {spec.name} ({spec.role})", file=sys.stderr)
                count += 1
            except Exception as e:
                print(f"[registry] 构建 {spec.name} 失败: {e}", file=sys.stderr)
        return count
