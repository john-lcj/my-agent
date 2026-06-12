"""find_files skill:按通配符递归查找文件。"""
from __future__ import annotations

import fnmatch
import os

from core.types import CapabilityResult

SCHEMA = {
    "type": "object",
    "properties": {
        "pattern": {"type": "string", "description": "文件名通配,如 *.py、index.*"},
        "path": {"type": "string", "description": "起始目录,默认当前目录"},
        "max_results": {"type": "integer", "description": "最多返回数,默认 100"},
    },
    "required": ["pattern"],
}

_SKIP = {".venv", "venv", ".git", "__pycache__", "node_modules",
         ".pytest_cache", ".idea", ".vscode"}


async def run(args: dict, ctx) -> CapabilityResult:
    pattern = str(args.get("pattern", "")).strip()
    if not pattern:
        return CapabilityResult(ok=False, error="缺少 pattern")
    root = os.path.expanduser(str(args.get("path") or "."))
    if not os.path.isdir(root):
        return CapabilityResult(ok=False, error=f"目录不存在:{root}")
    try:
        max_results = max(1, min(int(args.get("max_results") or 100), 500))
    except (TypeError, ValueError):
        max_results = 100

    found: list[str] = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _SKIP and not d.startswith(".")]
        for fn in files:
            if fnmatch.fnmatch(fn, pattern):
                found.append(os.path.relpath(os.path.join(dirpath, fn), root))
                if len(found) >= max_results:
                    break
        if len(found) >= max_results:
            break

    if not found:
        return CapabilityResult(ok=True, output=f"未找到匹配 {pattern} 的文件。")
    found.sort()
    capped = "(已达上限)" if len(found) >= max_results else ""
    return CapabilityResult(ok=True, output=f"找到 {len(found)} 个文件{capped}:\n"
                            + "\n".join("  " + p for p in found))
