"""table_format skill:CSV/TSV 文本 → Markdown 表格。"""
from __future__ import annotations

import csv
import io

from core.types import CapabilityResult

SCHEMA = {
    "type": "object",
    "properties": {
        "data": {"type": "string", "description": "带表头的 CSV/TSV 文本"},
        "delimiter": {"type": "string", "description": "分隔符,留空自动识别"},
    },
    "required": ["data"],
}


async def run(args: dict, ctx) -> CapabilityResult:
    data = str(args.get("data", "")).strip()
    if not data:
        return CapabilityResult(ok=False, error="缺少 data")
    delim = args.get("delimiter")
    if not delim:
        first = data.splitlines()[0]
        delim = "\t" if "\t" in first else ","
    delim = str(delim)[0]

    rows = [r for r in csv.reader(io.StringIO(data), delimiter=delim)
            if any(str(c).strip() for c in r)]
    if not rows:
        return CapabilityResult(ok=True, output="(空表)")

    ncol = max(len(r) for r in rows)
    rows = [r + [""] * (ncol - len(r)) for r in rows]

    def esc(c: object) -> str:
        return str(c).replace("|", "\\|").strip()

    header, body = rows[0], rows[1:]
    out = ["| " + " | ".join(esc(c) for c in header) + " |",
           "| " + " | ".join("---" for _ in header) + " |"]
    for r in body:
        out.append("| " + " | ".join(esc(c) for c in r) + " |")
    return CapabilityResult(ok=True, output="\n".join(out))
