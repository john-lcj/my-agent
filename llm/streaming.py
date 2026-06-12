"""流式输出辅助 —— 各 adapter 共用。"""
from __future__ import annotations

from typing import Awaitable, Callable, Optional

EmitTokenFn = Callable[[str], Awaitable[None]]


async def emit_text_chunks(
    text: str,
    emit_token: Optional[EmitTokenFn],
    chunk_size: int = 8,
) -> None:
    if not emit_token or not text:
        return
    for i in range(0, len(text), chunk_size):
        await emit_token(text[i:i + chunk_size])
