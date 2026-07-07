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


def _scope_of(ctx: Any) -> str:
    """当前对话的记忆隔离键 '渠道|项目'。

    优先用 server 注入的 ctx.mem_scope;缺省时退回 渠道('email|'/'scheduler|'),
    保证每个对接(web/邮件/定时)各自独立;'' 表示全局。
    """
    s = getattr(ctx, "mem_scope", None)
    if s is not None:
        return str(s)
    ch = getattr(getattr(ctx, "identity", None), "channel", "") or ""
    return f"{ch}|" if ch else ""


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
            "content": {"type": "string", "description": "Content to remember in one sentence"},
            "kind": {"type": "string",
                     "description": "Memory kind: fact, preference, or episode; defaults to fact"},
            "importance": {"type": "number",
                           "description": "Importance from 0 to 1; higher means more durable. Identity, preferences, long-term goals, and important facts default to 0.8"},
            "source": {"type": "string",
                       "description": "Source: user for explicit statements or agent for inference; defaults to agent"},
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
                                 scope=_scope_of(ctx),
                                 importance=max(0.0, min(1.0, importance))))
        except Exception as e:
            return CapabilityResult(ok=False, error=str(e))
        tag = "用户确认" if source == "user" else "agent推断"
        return CapabilityResult(ok=True, output=f"已记住({tag}):{content}")


class RecallMemory(Tool):
    name = "memory.recall"
    risk = Risk.READ
    description = "Recall relevant facts, preferences, or episodes from long-term memory by keyword."
    schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Recall query; empty returns the most important items"},
            "k": {"type": "integer", "description": "Number of results to return; defaults to 5"},
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
            items = mem.retrieve(query, k=k, scope=_scope_of(ctx))
        except Exception as e:
            return CapabilityResult(ok=False, error=str(e))
        if not items:
            return CapabilityResult(ok=True, output="(没有找到相关记忆)")
        src_label = {"user": "用户", "agent": "推断"}
        lines = []
        for it in items:
            stale = getattr(it, "stale", False)
            prefix = "【需刷新·stale】 " if stale else ""
            lines.append(f"- {prefix}[{it.kind}|{src_label.get(it.source, it.source)}] {it.content}")
        return CapabilityResult(ok=True, output="\n".join(lines))
