"""pdf_extract skill:从 PDF 提取文本(pypdf 优先,pdfplumber 兜底)。"""
from __future__ import annotations

import os

from core.types import CapabilityResult

SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "PDF 文件路径"},
        "pages": {"type": "string", "description": "页码范围,如 1-5 或 3;留空读全部"},
        "max_chars": {"type": "number", "description": "最多返回字符数,默认 8000"},
    },
    "required": ["path"],
}


def _parse_pages(spec: str, total: int) -> list[int]:
    spec = (spec or "").strip()
    if not spec:
        return list(range(total))
    out: set[int] = set()
    for part in spec.replace("，", ",").split(","):
        part = part.strip()
        if "-" in part:
            a, _, b = part.partition("-")
            try:
                for i in range(int(a) - 1, int(b)):
                    if 0 <= i < total:
                        out.add(i)
            except ValueError:
                continue
        elif part.isdigit():
            i = int(part) - 1
            if 0 <= i < total:
                out.add(i)
    return sorted(out) or list(range(total))


async def run(args: dict, ctx) -> CapabilityResult:
    path = os.path.expanduser(str(args.get("path", "")).strip())
    if not path:
        return CapabilityResult(ok=False, error="缺少参数 path")
    if not os.path.isfile(path):
        return CapabilityResult(ok=False, error=f"文件不存在:{path}")
    try:
        max_chars = int(args.get("max_chars", 8000))
    except (TypeError, ValueError):
        max_chars = 8000

    text = ""
    used = ""
    try:  # 首选 pypdf
        from pypdf import PdfReader
        reader = PdfReader(path)
        idxs = _parse_pages(str(args.get("pages", "")), len(reader.pages))
        text = "\n".join((reader.pages[i].extract_text() or "") for i in idxs)
        used = f"pypdf · 取 {len(idxs)}/{len(reader.pages)} 页"
    except Exception:
        try:  # 兜底 pdfplumber
            import pdfplumber
            with pdfplumber.open(path) as pdf:
                idxs = _parse_pages(str(args.get("pages", "")), len(pdf.pages))
                text = "\n".join((pdf.pages[i].extract_text() or "") for i in idxs)
                used = f"pdfplumber · 取 {len(idxs)}/{len(pdf.pages)} 页"
        except Exception as e:
            return CapabilityResult(ok=False, error=f"PDF 解析失败(需 pypdf 或 pdfplumber):{e}")

    text = text.strip()
    if not text:
        return CapabilityResult(ok=True, output=f"({used})未提取到文本——可能是扫描件(图片),需 OCR。")
    truncated = len(text) > max_chars
    body = text[:max_chars] + ("\n…(已截断)" if truncated else "")
    return CapabilityResult(ok=True, output=f"({used},共 {len(text)} 字)\n\n{body}")
