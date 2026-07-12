"""Governed command runner with an explicit local autonomous mode."""
from __future__ import annotations

import asyncio
import json
import os
import platform
from typing import Any

from core.types import CapabilityResult, Risk
from governance.sandbox import run_async
from governance.workspace import resolve_path


class RunShell:
    name = "shell.run"
    risk = Risk.DESTRUCTIVE
    description = (
        "Run an administrator-configured command ID. When local autonomous computer access is enabled, "
        "the command field may contain a raw shell command and runs without an OS sandbox."
    )
    schema = {
        "type": "object",
        "properties": {
            "command_id": {"type": "string", "description": "Exact ID from AGENT_APPROVED_SHELL_COMMANDS_JSON."},
            "command": {"type": "string", "description": "Raw shell command; available only in local autonomous mode."},
            "cwd": {"type": "string", "description": "Working directory for a raw autonomous command."},
            "timeout": {"type": "number", "description": "超时秒数,默认 30"},
        },
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        command = str(args.get("command", "")).strip()
        if command:
            if os.environ.get("CAPTAIN_AUTONOMOUS_ACCESS", "") != "1" or os.environ.get("CAPTAIN_DESKTOP", "") != "1":
                return CapabilityResult(ok=False, error="raw shell commands require local autonomous computer access")
            return await _run_raw_command(command, args)
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


async def _run_raw_command(command: str, args: dict) -> CapabilityResult:
    try:
        timeout = max(1.0, min(float(args.get("timeout", 120)), 3600.0))
    except (TypeError, ValueError):
        timeout = 120.0
    cwd_raw = str(args.get("cwd") or os.environ.get("AGENT_SHELL_CWD", "") or ".")
    cwd, error = resolve_path(cwd_raw, require_exists=True)
    if error or not os.path.isdir(cwd):
        return CapabilityResult(ok=False, error=error or "working directory is invalid")
    if platform.system() == "Windows":
        argv = ["powershell", "-NoProfile", "-NonInteractive", "-Command", command]
    else:
        argv = ["/bin/zsh", "-lc", command]
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=cwd,
            env=os.environ.copy(),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return CapabilityResult(ok=False, error=f"command timed out after {timeout:g}s")
    except Exception as exc:
        return CapabilityResult(ok=False, error=str(exc))
    limit = 256_000
    stdout = out.decode("utf-8", "replace")[-limit:]
    stderr = err.decode("utf-8", "replace")[-limit:]
    body = stdout + (f"\n[stderr]\n{stderr}" if stderr else "")
    return CapabilityResult(
        ok=proc.returncode == 0,
        output=body,
        error=None if proc.returncode == 0 else f"command exited {proc.returncode}",
    )
