"""guidance 型 skill 共用：从 SKILL.md 按章节切片返回。"""
from __future__ import annotations

import os
import re

_MAX_CHARS = 28_000


def read_skill_body(skill_dir: str) -> str:
    path = os.path.join(skill_dir, "SKILL.md")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4 :].lstrip()
    return text


def slice_between(body: str, start_re: str, end_re: str | None = None) -> str:
    m = re.search(start_re, body, re.MULTILINE)
    if not m:
        return ""
    start = m.start()
    if end_re:
        m2 = re.search(end_re, body[m.end() :], re.MULTILINE)
        end = m.end() + m2.start() if m2 else len(body)
    else:
        end = len(body)
    return body[start:end].strip()


def cap(text: str, limit: int = _MAX_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 80] + "\n\n…(已截断，可用 action=full 获取更完整片段)"
