"""Residual command runner for explicitly configured, exact argv operations."""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from core.types import CapabilityResult, Risk
from governance.sandbox import run_async
from governance.workspace import resolve_path


class RunShell:
    name = "shell.run"
    risk = Risk.DESTRUCTIVE
    description = "Run an administrator-configured command ID after explicit approval."
    schema = {
        "type": "object",
        "properties": {
            "command_id": {"type": "string", "description": "Exact ID from AGENT_APPROVED_SHELL_COMMANDS_JSON."},
            "timeout": {"type": "number", "description": "超时秒数,默认 30"},
        },
        "required": ["command_id"],
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        if str(args.get("command", "")).strip():
            return CapabilityResult(ok=False, error="raw shell commands are disabled; use a typed capability or command_id")
        command_id = str(args.get("command_id", "")).strip()
        timeout = float(args.get("timeout", 30))
        if not command_id:
            return CapabilityResult(ok=False, error="missing command_id")
        try:
            configured = json.loads(os.environ.get("AGENT_APPROVED_SHELL_COMMANDS_JSON", "{}"))
        except json.JSONDecodeError:
            return CapabilityResult(ok=False, error="AGENT_APPROVED_SHELL_COMMANDS_JSON is invalid")
        argv = configured.get(command_id) if isinstance(configured, dict) else None
        if not isinstance(argv, list) or not argv or not all(isinstance(x, str) and x for x in argv):
            return CapabilityResult(ok=False, error="command_id is not approved by the administrator")

        cwd_raw = os.environ.get("AGENT_SHELL_CWD", "").strip() or "."
        cwd, error = resolve_path(cwd_raw, require_exists=True)
        if error or not os.path.isdir(cwd):
            return CapabilityResult(ok=False, error=error or "working directory is invalid")
        try:
            ok, body, error = await run_async(argv, workspace=cwd, timeout=timeout)
        except Exception as e:
            return CapabilityResult(ok=False, error=str(e))
        return CapabilityResult(ok=ok, output=body, error=error or None)
