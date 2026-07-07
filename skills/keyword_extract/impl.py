"""keyword_extract: 词频关键词提取。"""
from __future__ import annotations

import re
from collections import Counter

from core.types import CapabilityResult

SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string", "description": "Source text"},
        "top_n": {"type": "integer", "description": "Number of results to return", "default": 10},
    },
    "required": ["text"],
}

_STOP = frozenset(
    "的 了 是 在 和 与 及 或 而 也 都 就 还 又 及 等 中 对 为 以 于 从 到 被 把 "
    "一个 我们 你们 他们 这个 那个 可以 已经 进行 通过 以及 因为 所以 如果 但是 "
    "the a an and or but is are was were be been being to of in on at for with by from "
    "this that these those it its as not".split()
)

_TOKEN = re.compile(r"[\u4e00-\u9fff]{2,}|[a-zA-Z]{3,}")


def _tokens(text: str) -> list[str]:
    found = _TOKEN.findall(text.lower())
    return [t for t in found if t not in _STOP]


async def run(args: dict, ctx) -> CapabilityResult:
    text = str(args.get("text", "")).strip()
    if not text:
        return CapabilityResult(ok=False, error="缺少 text")
    top_n = int(args.get("top_n") or 10)
    top_n = max(1, min(top_n, 30))

    counts = Counter(_tokens(text))
    if not counts:
        return CapabilityResult(ok=True, output="未提取到有效关键词(文本过短或均为停用词)")

    lines = [f"关键词 Top{top_n} (词频):"]
    for word, n in counts.most_common(top_n):
        lines.append(f"  {word}: {n}")
    return CapabilityResult(ok=True, output="\n".join(lines))
