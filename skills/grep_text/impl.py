"""grep_text skill:在目录里跨文件搜索字符串/正则。"""
from __future__ import annotations

import os
import re

from core.types import CapabilityResult
from governance.workspace import resolve_path

SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "String or regular expression to search for"},
        "path": {"type": "string", "description": "Search directory; defaults to current directory"},
        "regex": {"type": "boolean", "description": "Whether query is a regex; defaults to false for literal matching"},
        "ext": {"type": "string", "description": "Only search one extension, such as .py"},
        "max_results": {"type": "integer", "description": "Maximum matching lines to return; defaults to 50"},
    },
    "required": ["query"],
}

_SKIP = {".venv", "venv", ".git", "__pycache__", "node_modules",
         ".pytest_cache", "logs", ".idea", ".vscode"}


async def run(args: dict, ctx) -> CapabilityResult:
    query = str(args.get("query", "")).strip()
    if not query:
        return CapabilityResult(ok=False, error="缺少 query")
    root, error = resolve_path(str(args.get("path") or "."), require_exists=True)
    if error or not os.path.isdir(root):
        return CapabilityResult(ok=False, error=f"目录不存在:{root}")
    ext = str(args.get("ext") or "").strip()
    try:
        max_results = max(1, min(int(args.get("max_results") or 50), 300))
    except (TypeError, ValueError):
        max_results = 50
    try:
        pat = re.compile(query if args.get("regex") else re.escape(query))
    except re.error as e:
        return CapabilityResult(ok=False, error=f"正则无效:{e}")

    hits: list[str] = []
    scanned = 0
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in _SKIP and not d.startswith(".")]
        for fn in files:
            if ext and not fn.endswith(ext):
                continue
            fp = os.path.join(dirpath, fn)
            try:
                if os.path.getsize(fp) > 2_000_000:
                    continue
                with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                    for i, line in enumerate(f, 1):
                        if pat.search(line):
                            rel = os.path.relpath(fp, root)
                            hits.append(f"{rel}:{i}: {line.strip()[:200]}")
                            if len(hits) >= max_results:
                                break
            except Exception:
                continue
            scanned += 1
            if len(hits) >= max_results:
                break
        if len(hits) >= max_results:
            break

    if not hits:
        return CapabilityResult(ok=True, output=f"未找到匹配(扫描 {scanned} 个文件)。")
    capped = "(已达上限)" if len(hits) >= max_results else ""
    return CapabilityResult(ok=True, output=f"找到 {len(hits)} 处匹配{capped}:\n" + "\n".join(hits))
