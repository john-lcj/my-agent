"""json_tools skill:校验 / 美化 / 压缩 JSON,或列顶层键。"""
from __future__ import annotations

import json

from core.types import CapabilityResult

SCHEMA = {
    "type": "object",
    "properties": {
        "json_text": {"type": "string", "description": "JSON 文本"},
        "action": {
            "type": "string",
            "enum": ["validate", "pretty", "minify", "keys"],
            "description": "validate校验 / pretty美化 / minify压缩 / keys列顶层键",
        },
    },
    "required": ["json_text"],
}


async def run(args: dict, ctx) -> CapabilityResult:
    raw = str(args.get("json_text", ""))
    action = str(args.get("action") or "pretty").lower()
    if not raw.strip():
        return CapabilityResult(ok=False, error="缺少 json_text")
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as e:
        return CapabilityResult(ok=False, error=f"JSON 非法:第 {e.lineno} 行第 {e.colno} 列 — {e.msg}")

    if action == "validate":
        return CapabilityResult(ok=True, output="✓ JSON 合法")
    if action == "minify":
        return CapabilityResult(ok=True,
                                output=json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
    if action == "keys":
        if isinstance(obj, dict):
            body = "\n".join(f"  {k}: {type(v).__name__}" for k, v in obj.items())
            return CapabilityResult(ok=True, output=f"顶层键({len(obj)}):\n{body}")
        return CapabilityResult(ok=True, output=f"顶层是 {type(obj).__name__}(非对象,无顶层键)")
    return CapabilityResult(ok=True, output=json.dumps(obj, ensure_ascii=False, indent=2))
