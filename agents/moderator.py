"""主持人 —— 圆桌会议的发言调度与收敛判定。

基础实现:轮流发言(round-robin)。收敛判定留一个简单启发(最近两条高度重复
则视为收敛),真实场景可换成"由一个主持人模型判断是否达成共识"。
"""
from __future__ import annotations

from core.types import Message


class RoundRobinModerator:
    def next_speaker(self, agents: list, turn: int):
        return agents[turn % len(agents)]

    def has_converged(self, conversation: list[Message]) -> bool:
        if len(conversation) < 2:
            return False
        a, b = conversation[-1].content.strip(), conversation[-2].content.strip()
        # 最近两条几乎一致 -> 认为讨论已无新增信息。
        return bool(a) and a == b
