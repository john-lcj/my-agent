"""工具 = 一种 Capability。这里提供一个便于书写工具的基类。

新增工具只需:继承 Tool,声明 name/risk/description/schema,实现 invoke。
然后在组合根(main.py)注册一行即可,主循环与治理层无需改动。
"""
from __future__ import annotations

from typing import Any

from core.types import CapabilityResult, Risk


class Tool:
    name: str = ""
    risk: Risk = Risk.READ
    description: str = ""
    schema: dict = {"type": "object", "properties": {}}

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        raise NotImplementedError
