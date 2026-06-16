"""长期记忆能力 —— 让 agent 显式地"记住"与"回忆"。

memory.remember 风险定为 WRITE:写入会持久污染未来所有对话,默认需确认(治理层)。
memory.recall 仍为 READ:只读检索,不打扰。

每条记忆带 source 标记(user=用户明说 / agent=agent 推断),便于日后审计可信度。
"""
from __future__ import annotations

from typing import Any

from capabilities.tools.base import Tool
from core.types import CapabilityResult, Risk
from memory.base import MemoryItem


class RememberMemory(Tool):
    name = "memory.remember"
    risk = Risk.WRITE         # 持久写入 → 默认 ASK;低重要性可 policy 自动放行
    description = (
        "把一条值得长期记住的事实/偏好存入长期记忆。"
        "用户亲口说的用 source=user;agent 自己推断的用 source=agent(默认)。"
    )
    schema = {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "要记住的内容(一句话)"},
            "kind": {"type": "string",
                     "description": "类型: fact / preference / episode,默认 fact"},
            "importance": {"type": "number",
                           "description": "重要性 0~1,越高越不易被遗忘。称呼/偏好/长期目标/重要事实等身份信息默认 0.8"},
            "source": {"type": "string",
                       "description": "来源: user(用户明说) 或 agent(推断),默认 agent"},
        },
        "required": ["content"],
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        mem = getattr(ctx, "longterm", None)
        if mem is None:
            return CapabilityResult(ok=False, error="未配置长期记忆后端")
        content = str(args.get("content", "")).strip()
        if not content:
            return CapabilityResult(ok=False, error="缺少参数 content")
        kind = str(args.get("kind", "fact")) or "fact"
        source = str(args.get("source", "agent")).strip().lower()
        if source not in ("user", "agent"):
            source = "agent"
        # 身份类信息(称呼/偏好/长期目标/重要事实)最值得记牢,默认重要度高(0.8)。
        try:
            importance = float(args.get("importance", 0.8))
        except (TypeError, ValueError):
            importance = 0.8
        try:
            mem.store(MemoryItem(kind=kind, content=content, source=source,
                                 importance=max(0.0, min(1.0, importance))))
        except Exception as e:
            return CapabilityResult(ok=False, error=str(e))
        tag = "用户确认" if source == "user" else "agent推断"
        return CapabilityResult(ok=True, output=f"已记住({tag}):{content}")


class RecallMemory(Tool):
    name = "memory.recall"
    risk = Risk.READ
    description = "按关键词从长期记忆里检索相关的事实/偏好/经历。"
    schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "检索关键词;留空则取最重要的若干条"},
            "k": {"type": "integer", "description": "返回条数,默认 5"},
        },
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        mem = getattr(ctx, "longterm", None)
        if mem is None:
            return CapabilityResult(ok=False, error="未配置长期记忆后端")
        query = str(args.get("query", "")).strip()
        try:
            k = int(args.get("k", 5))
        except (TypeError, ValueError):
            k = 5
        try:
            items = mem.retrieve(query, k=k)
        except Exception as e:
            return CapabilityResult(ok=False, error=str(e))
        if not items:
            return CapabilityResult(ok=True, output="(没有找到相关记忆)")
        src_label = {"user": "用户", "agent": "推断"}
        lines = [f"- [{it.kind}|{src_label.get(it.source, it.source)}] {it.content}"
                 for it in items]
        return CapabilityResult(ok=True, output="\n".join(lines))
