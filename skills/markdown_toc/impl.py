"""markdown_toc skill:从 Markdown 标题生成带锚点的目录。"""
from __future__ import annotations

import re

from core.types import CapabilityResult

SCHEMA = {
    "type": "object",
    "properties": {
        "markdown": {"type": "string", "description": "Markdown 文本"},
        "max_level": {"type": "integer", "description": "最大标题层级,默认 3"},
    },
    "required": ["markdown"],
}

_H = re.compile(r"^(#{1,6})\s+(.+?)\s*#*$")


def _slug(title: str) -> str:
    s = re.sub(r"[^\w一-鿿\- ]", "", title).strip().lower()
    return s.replace(" ", "-")


async def run(args: dict, ctx) -> CapabilityResult:
    md = str(args.get("markdown", ""))
    if not md.strip():
        return CapabilityResult(ok=False, error="缺少 markdown")
    try:
        max_level = int(args.get("max_level") or 3)
    except (TypeError, ValueError):
        max_level = 3

    lines: list[str] = []
    in_code = False
    for line in md.splitlines():
        if line.strip().startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        m = _H.match(line)
        if m:
            level = len(m.group(1))
            title = m.group(2).strip()
            if level <= max_level:
                lines.append("  " * (level - 1) + f"- [{title}](#{_slug(title)})")
    if not lines:
        return CapabilityResult(ok=True, output="(未找到标题)")
    return CapabilityResult(ok=True, output="\n".join(lines))
