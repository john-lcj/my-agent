"""file_append skill:向文件末尾追加内容(不覆盖)。"""
from __future__ import annotations

import os

from core.types import CapabilityResult
from governance.workspace import resolve_path

RISK = "WRITE"

SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "File path"},
        "content": {"type": "string", "description": "Text to append"},
        "newline": {"type": "boolean", "description": "Whether to insert a newline before appending; defaults to true"},
    },
    "required": ["path", "content"],
}


async def run(args: dict, ctx) -> CapabilityResult:
    path, error = resolve_path(str(args.get("path", "")))
    content = str(args.get("content", ""))
    if error:
        return CapabilityResult(ok=False, error=error)
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
