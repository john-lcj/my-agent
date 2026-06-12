"""file_edit skill:在文件里精确查找替换(原地编辑)。"""
from __future__ import annotations

import os

from core.types import CapabilityResult

SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "文件路径"},
        "old": {"type": "string", "description": "要替换掉的原文本(默认需唯一)"},
        "new": {"type": "string", "description": "替换成的新文本"},
        "replace_all": {"type": "boolean", "description": "替换全部匹配,默认 false"},
    },
    "required": ["path", "old", "new"],
}


async def run(args: dict, ctx) -> CapabilityResult:
    path = os.path.expanduser(str(args.get("path", "")))
    old = str(args.get("old", ""))
    new = str(args.get("new", ""))
    if not path:
        return CapabilityResult(ok=False, error="缺少 path")
    if not old:
        return CapabilityResult(ok=False, error="缺少 old(要替换的原文本)")
    if not os.path.isfile(path):
        return CapabilityResult(ok=False, error=f"文件不存在:{path}")
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        return CapabilityResult(ok=False, error=f"读取失败:{e}")

    count = content.count(old)
    if count == 0:
        return CapabilityResult(ok=False, error="未找到要替换的原文本(old 不在文件中)")
    replace_all = bool(args.get("replace_all"))
    if count > 1 and not replace_all:
        return CapabilityResult(
            ok=False,
            error=f"原文本出现 {count} 次,不唯一。请在 old 里加上下文使其唯一,或设 replace_all=true。")

    new_content = content.replace(old, new) if replace_all else content.replace(old, new, 1)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)
    except Exception as e:
        return CapabilityResult(ok=False, error=f"写入失败:{e}")
    n = count if replace_all else 1
    return CapabilityResult(ok=True, output=f"已在 {path} 替换 {n} 处。")
