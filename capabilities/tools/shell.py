"""命令执行工具 —— 真实实现。

默认归为 DESTRUCTIVE(总是询问):执行命令是最容易出事的能力之一。
真正的"绝对禁止"项(rm -rf / force push 等)由 policy.yaml 的硬边界拦截,
这里只负责在通过治理后安全地跑命令并捕获输出。
"""
from __future__ import annotations

import asyncio
from typing import Any

from core.types import CapabilityResult, Risk


class RunShell:
    name = "shell.run"
    risk = Risk.DESTRUCTIVE
    description = "在 shell 中执行一条命令,返回 stdout/stderr。"
    schema = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "要执行的命令"},
            "timeout": {"type": "number", "description": "超时秒数,默认 30"},
        },
        "required": ["command"],
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        command = str(args.get("command", "")).strip()
        timeout = float(args.get("timeout", 30))
        if not command:
            return CapabilityResult(ok=False, error="缺少参数 command")
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            return CapabilityResult(ok=False, error=f"命令超时(>{timeout}s)")
        except Exception as e:
            return CapabilityResult(ok=False, error=str(e))

        stdout = out.decode("utf-8", "replace")
        stderr = err.decode("utf-8", "replace")
        body = stdout + (f"\n[stderr]\n{stderr}" if stderr else "")
        return CapabilityResult(ok=proc.returncode == 0, output=body,
                                error=None if proc.returncode == 0 else f"exit={proc.returncode}")
