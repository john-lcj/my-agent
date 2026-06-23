"""记忆接口 —— 长期记忆(情景/语义)的统一存取契约。

记忆不是一种东西,而是四种:
  工作记忆(当前对话窗口)   -> memory/working.py
  情景记忆("上次做过啥")    -> 长期存储,可检索
  语义记忆(事实/偏好/知识)  -> 向量检索(RAG)
  程序记忆(学到的做事方式)  -> 进阶,暂不做

本接口面向"长期记忆"(情景 + 语义)。后端可从 SQLite 升级到向量库,
对上层透明。retrieve 之外特意保留 forget:记忆要主动管理,不是只进不出。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable
import time


@dataclass
class MemoryItem:
    kind: str                 # 'fact' | 'preference' | 'episode'
    content: str
    importance: float = 0.5   # 用于遗忘:低分优先清理
    source: str = "agent"     # 'user' 用户明说 | 'agent' agent 推断 —— 影响可信度
    scope: str = ""           # 归属隔离键 '渠道|项目';'' = 全局(偏好/经验,跨对接始终可见)
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)


@runtime_checkable
class Memory(Protocol):
    def store(self, item: MemoryItem) -> None: ...
    def retrieve(self, query: str, k: int = 5, scope: str | None = None) -> list[MemoryItem]: ...
    def forget(self) -> None: ...
