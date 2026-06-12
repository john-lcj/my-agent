"""程序记忆能力 —— 结构化 KV 读写。"""
from __future__ import annotations

import json
from typing import Any

from capabilities.tools.base import Tool
from core.types import CapabilityResult, Risk


def _scope(ctx: Any, args: dict) -> str:
    explicit = str(args.get("scope", "")).strip()
    if explicit:
        return explicit
    ident = getattr(ctx, "identity", None)
    if ident is not None and getattr(ident, "subject_id", None):
        return str(ident.subject_id)
    return "global"


def _store(ctx: Any):
    return getattr(ctx, "program", None)


class ProgramRemember(Tool):
    name = "program.remember"
    risk = Risk.WRITE
    description = "写入一条结构化程序记忆(键值对),供后续精确 recall。"
    schema = {
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "记忆键,如 prefs.reply_style"},
            "value": {"description": "任意 JSON 可序列化值"},
            "scope": {"type": "string", "description": "作用域,默认当前用户 subject_id"},
        },
        "required": ["key", "value"],
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        store = _store(ctx)
        if store is None:
            return CapabilityResult(ok=False, error="未配置程序记忆后端")
        key = str(args.get("key", "")).strip()
        if not key:
            return CapabilityResult(ok=False, error="缺少 key")
        if "value" not in args:
            return CapabilityResult(ok=False, error="缺少 value")
        try:
            store.set(_scope(ctx, args), key, args["value"])
        except Exception as e:
            return CapabilityResult(ok=False, error=str(e))
        return CapabilityResult(ok=True, output=f"已写入 program:{key}")


class ProgramRecall(Tool):
    name = "program.recall"
    risk = Risk.READ
    description = "读取一条程序记忆。"
    schema = {
        "type": "object",
        "properties": {
            "key": {"type": "string"},
            "scope": {"type": "string"},
        },
        "required": ["key"],
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        store = _store(ctx)
        if store is None:
            return CapabilityResult(ok=False, error="未配置程序记忆后端")
        key = str(args.get("key", "")).strip()
        val = store.get(_scope(ctx, args), key)
        if val is None:
            return CapabilityResult(ok=True, output=f"(无 program 记忆: {key})")
        return CapabilityResult(ok=True, output=json.dumps(val, ensure_ascii=False))


class ProgramList(Tool):
    name = "program.list"
    risk = Risk.READ
    description = "列出当前作用域下的程序记忆键(可按前缀过滤)。"
    schema = {
        "type": "object",
        "properties": {
            "prefix": {"type": "string", "description": "键前缀,可选"},
            "scope": {"type": "string"},
        },
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        store = _store(ctx)
        if store is None:
            return CapabilityResult(ok=False, error="未配置程序记忆后端")
        prefix = str(args.get("prefix", ""))
        keys = store.list_keys(_scope(ctx, args), prefix)
        if not keys:
            return CapabilityResult(ok=True, output="(无匹配键)")
        return CapabilityResult(ok=True, output="\n".join(f"- {k}" for k in keys))
