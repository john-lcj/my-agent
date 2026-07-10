"""Typed developer operations that replace routine shell usage."""
from __future__ import annotations

from typing import Any

from capabilities.tools.base import Tool
from core.test_runner import run_pytest
from core.types import CapabilityResult, Risk


class RunTests(Tool):
    name = "dev.run_tests"
    risk = Risk.WRITE
    description = "Run a pytest file or test node below the workspace tests directory."
    schema = {
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": "Test path below tests/, optionally with ::test_name.",
            },
            "timeout": {"type": "integer", "description": "Timeout in seconds, up to 120."},
        },
        "required": ["target"],
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        try:
            timeout = max(1, min(int(args.get("timeout", 120) or 120), 120))
        except (TypeError, ValueError):
            timeout = 120
        ok, output, error = run_pytest(str(args.get("target", "")), timeout=timeout)
        return CapabilityResult(ok=ok, output=output, error=error or None)
