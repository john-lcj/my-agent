"""readability_score: 句长与简易可读性评分。"""
from __future__ import annotations

import re

from core.types import CapabilityResult

SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string", "description": "待分析文本"},
        "lang": {"type": "string", "description": "zh 或 auto", "default": "auto"},
    },
    "required": ["text"],
}

_SENT_SPLIT = re.compile(r"[。！？!?；;\n]+")
_LONG_THRESHOLD = 40


def _split_sentences(text: str) -> list[str]:
    parts = _SENT_SPLIT.split(text.strip())
    return [p.strip() for p in parts if p.strip()]


async def run(args: dict, ctx) -> CapabilityResult:
    text = str(args.get("text", "")).strip()
    if not text:
        return CapabilityResult(ok=False, error="缺少 text")

    sentences = _split_sentences(text)
    if not sentences:
        sentences = [text]

    lengths = [len(s) for s in sentences]
    avg_len = sum(lengths) / len(lengths)
    long_count = sum(1 for n in lengths if n > _LONG_THRESHOLD)
    long_ratio = long_count / len(lengths)
    chars = len(text)

    # 简易分: 句越短、过长句越少分越高 (0-100)
    penalty = min(50, avg_len * 0.8) + long_ratio * 30
    score = max(0, min(100, int(100 - penalty)))

    level = "优秀" if score >= 75 else ("良好" if score >= 55 else "需精简")

    lines = [
        f"可读性评分={score}/100 ({level})",
        f"字符数={chars}, 句数={len(sentences)}, 平均句长={avg_len:.1f}字",
        f"过长句(>{_LONG_THRESHOLD}字)={long_count} ({long_ratio:.0%})",
    ]
    if long_count:
        longest = max(sentences, key=len)
        lines.append(f"最长句摘录: {longest[:80]}{'…' if len(longest) > 80 else ''}")

    return CapabilityResult(ok=True, output="\n".join(lines))
