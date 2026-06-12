"""text_stats skill 实现:中英文友好的文本统计。"""
from __future__ import annotations

import re

from core.types import CapabilityResult

SCHEMA = {
    "type": "object",
    "properties": {"text": {"type": "string", "description": "要统计的文本"}},
    "required": ["text"],
}

_CJK = re.compile(r"[一-鿿㐀-䶿]")          # 中日韩统一表意文字
_EN_WORD = re.compile(r"[A-Za-z][A-Za-z'\-]*")             # 英文单词
_SENT = re.compile(r"[。！？!?；;]+|\n+")


async def run(args: dict, ctx) -> CapabilityResult:
    text = str(args.get("text", ""))
    if not text:
        return CapabilityResult(ok=False, error="缺少 text")

    chars = len(text)
    chars_no_space = len(re.sub(r"\s", "", text))
    cjk = len(_CJK.findall(text))
    en_words = len(_EN_WORD.findall(text))
    word_count = cjk + en_words                              # 中文按字、英文按词
    lines = len(text.splitlines()) or (1 if text else 0)
    paragraphs = len([p for p in re.split(r"\n\s*\n", text.strip()) if p.strip()])
    sentences = len([s for s in _SENT.split(text) if s.strip()])
    # 阅读时长:中文约 300 字/分,英文约 200 词/分。
    minutes = cjk / 300 + en_words / 200
    read_time = (f"{round(minutes)} 分钟" if minutes >= 0.5 else "<1 分钟")

    out = [
        f"总字符={chars}(不含空白={chars_no_space})",
        f"字数={word_count}(中文字={cjk},英文词={en_words})",
        f"行数={lines},段落={paragraphs},句子≈{sentences}",
        f"预计阅读时长≈{read_time}",
    ]
    return CapabilityResult(ok=True, output="\n".join(out))
