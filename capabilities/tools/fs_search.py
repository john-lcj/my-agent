"""工作区内容检索能力 —— 让 agent「在我所有文件里找出相关的」,而不只读已知路径。

默认关键词/正则全文搜(快、零依赖);命中文件返回路径 + 命中行号 + 片段。
工作区根由 AGENT_WORKSPACE_ROOT 决定;只读、不弹确认。
"""
from __future__ import annotations

import os
import re
from typing import Any

from core.types import CapabilityResult, Risk

_SKIP_DIRS = {".git", ".venv", "__pycache__", "node_modules", ".pytest_cache",
              "my_agent.egg-info", ".cursor", "logs", "uploads", "snapshots"}
_TEXT_EXTS = {"py", "js", "ts", "md", "txt", "json", "yaml", "yml", "html", "htm",
              "css", "csv", "tsv", "sh", "toml", "ini", "cfg", "xml", "sql", "rs",
              "go", "java", "c", "cpp", "h"}
_MAX_BYTES = 1_000_000   # 单文件超过 1MB 跳过(避免读大二进制/日志)


def _base() -> str:
    b = os.environ.get("AGENT_WORKSPACE_ROOT", "").strip() or os.getcwd()
    return os.path.realpath(os.path.expanduser(b))


class FsSearch:
    name = "fs.search"
    risk = Risk.READ
    description = ("在工作区所有文件里按关键词/正则全文检索,找出相关文件和命中行。"
                  "用于'在我的项目里找出和 X 有关的地方',而不必先知道文件路径。")
    schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "要搜索的关键词或正则"},
            "regex": {"type": "boolean", "description": "query 是否按正则解析(默认否=子串)"},
            "glob": {"type": "string", "description": "可选:只搜匹配此通配的文件,如 *.py"},
            "max_results": {"type": "integer", "description": "最多返回命中数(默认 40)"},
        },
        "required": ["query"],
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        query = str(args.get("query", "")).strip()
        if not query:
            return CapabilityResult(ok=False, error="query 为空")
        use_regex = bool(args.get("regex"))
        glob = str(args.get("glob", "")).strip()
        limit = max(1, min(int(args.get("max_results", 40) or 40), 200))
        try:
            pat = re.compile(query if use_regex else re.escape(query), re.IGNORECASE)
        except re.error as e:
            return CapabilityResult(ok=False, error=f"正则非法: {e}")
        import fnmatch
        base = _base()
        hits: list[str] = []
        scanned = 0
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
            for name in files:
                if name.startswith("."):
                    continue
                if glob and not fnmatch.fnmatch(name, glob):
                    continue
                ext = os.path.splitext(name)[1].lstrip(".").lower()
                if not glob and ext not in _TEXT_EXTS:
                    continue
                full = os.path.join(root, name)
                try:
                    if os.path.getsize(full) > _MAX_BYTES:
                        continue
                    with open(full, "r", encoding="utf-8", errors="ignore") as f:
                        scanned += 1
                        for i, line in enumerate(f, 1):
                            if pat.search(line):
                                rel = os.path.relpath(full, base)
                                hits.append(f"{rel}:{i}: {line.strip()[:160]}")
                                if len(hits) >= limit:
                                    break
                except OSError:
                    continue
                if len(hits) >= limit:
                    break
            if len(hits) >= limit:
                break
        if not hits:
            return CapabilityResult(ok=True, output=f"在 {scanned} 个文件里没找到「{query}」。")
        head = f"命中 {len(hits)} 处(搜了 {scanned} 个文件):\n"
        return CapabilityResult(ok=True, output=head + "\n".join(hits))
