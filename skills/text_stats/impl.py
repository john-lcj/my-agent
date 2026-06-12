"""text_stats skill 实现:统计字符/词/行数。"""
from core.types import CapabilityResult

SCHEMA = {
    "type": "object",
    "properties": {"text": {"type": "string", "description": "要统计的文本"}},
    "required": ["text"],
}


async def run(args: dict, ctx) -> CapabilityResult:
    text = str(args.get("text", ""))
    chars = len(text)
    words = len(text.split())
    lines = len(text.splitlines()) or (1 if text else 0)
    return CapabilityResult(ok=True, output=f"字符={chars}, 词={words}, 行={lines}")
