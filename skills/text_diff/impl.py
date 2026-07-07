"""text_diff skill:对比两段文本,输出统一 diff + 相似度。"""
from __future__ import annotations

import difflib

from core.types import CapabilityResult

SCHEMA = {
    "type": "object",
    "properties": {
        "a": {"type": "string", "description": "Original text"},
        "b": {"type": "string", "description": "New text"},
    },
    "required": ["a", "b"],
}


async def run(args: dict, ctx) -> CapabilityResult:
    a = str(args.get("a", ""))
    b = str(args.get("b", ""))
    if not a and not b:
        return CapabilityResult(ok=False, error="缺少 a / b")

    diff = list(difflib.unified_diff(
        a.splitlines(), b.splitlines(), fromfile="原", tofile="新", lineterm=""))
    if not diff:
        return CapabilityResult(ok=True, output="两段文本完全一致。")

    adds = sum(1 for d in diff if d.startswith("+") and not d.startswith("+++"))
    dels = sum(1 for d in diff if d.startswith("-") and not d.startswith("---"))
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    head = f"相似度={ratio:.0%},新增 {adds} 行,删除 {dels} 行\n"
    body = "\n".join(diff[:200])
    if len(diff) > 200:
        body += "\n…(diff 过长已截断)"
    return CapabilityResult(ok=True, output=head + body)
