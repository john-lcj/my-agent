"""file_append skill:向文件末尾追加内容(不覆盖)。"""
from __future__ import annotations

import os

from core.types import CapabilityResult

SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "文件路径"},
        "content": {"type": "string", "description": "要追加的文本"},
        "newline": {"type": "boolean", "description": "追加前是否先补一个换行,默认 true"},
    },
    "required": ["path", "content"],
}


async def run(args: dict, ctx) -> CapabilityResult:
    path = os.path.expanduser(str(args.get("path", "")))
    content = str(args.get("content", ""))
    if not path:
        return CapabilityResult(ok=False, error="缺少 path")
    add_nl = args.get("newline", True)
    prefix = ""
    if add_nl and os.path.isfile(path) and os.path.getsize(path) > 0:
        prefix = "\n"
    try:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(prefix + content)
    except Exception as e:
        return CapabilityResult(ok=False, error=f"写入失败:{e}")
    return CapabilityResult(ok=True, output=f"已向 {path} 追加 {len(content)} 字符。")
