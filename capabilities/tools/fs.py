"""文件读写工具 —— 真实实现(单 agent 闭环用得上)。

读为 READ(永不打扰),写为 WRITE(默认询问,可授权放手)。
路径越界等硬约束由治理层(policy.yaml)负责,这里只做本职 I/O。
"""
from __future__ import annotations

import os
from typing import Any

from capabilities.tools.base import Tool
from core.types import CapabilityResult, Risk


class ReadFile(Tool):
    name = "fs.read"
    risk = Risk.READ
    description = "读取一个文本文件的内容。"
    schema = {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "文件路径"}},
        "required": ["path"],
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        path = os.path.expanduser(str(args.get("path", "")))
        if not path:
            return CapabilityResult(ok=False, error="缺少参数 path")
        if not os.path.isfile(path):
            return CapabilityResult(ok=False, error=f"文件不存在:{path}")
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            return CapabilityResult(ok=False, error=str(e))
        return CapabilityResult(ok=True, output=content)


class ListDir(Tool):
    name = "fs.list"
    risk = Risk.READ
    description = "列出某个目录下的文件与子目录(让 agent 先看看有什么再读)。"
    schema = {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "目录路径,默认当前目录"}},
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        path = os.path.expanduser(str(args.get("path", "."))) or "."
        if not os.path.isdir(path):
            return CapabilityResult(ok=False, error=f"目录不存在:{path}")
        try:
            entries = sorted(os.listdir(path))
        except Exception as e:
            return CapabilityResult(ok=False, error=str(e))
        lines = []
        for name in entries:
            full = os.path.join(path, name)
            lines.append(f"{'d' if os.path.isdir(full) else '-'} {name}")
        return CapabilityResult(ok=True, output="\n".join(lines) or "(空目录)")


class WriteFile(Tool):
    name = "fs.write"
    risk = Risk.WRITE
    description = "把内容写入文件(覆盖)。父目录不存在会自动创建。"
    schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径"},
            "content": {"type": "string", "description": "要写入的文本"},
        },
        "required": ["path", "content"],
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        path = os.path.expanduser(str(args.get("path", "")))
        content = str(args.get("content", ""))
        if not path:
            return CapabilityResult(ok=False, error="缺少参数 path")
        try:
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception as e:
            return CapabilityResult(ok=False, error=str(e))
        return CapabilityResult(ok=True, output=f"已写入 {len(content)} 字符到 {path}")
