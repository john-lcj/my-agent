"""Captain 阶段限制 —— 模式 A+：主 agent 先尝试，步数用尽再升级专家。"""
from __future__ import annotations

from core.context import Context
from core.types import Role


class CaptainPhaseExhausted(Exception):
    """Captain 在 captain_phase_limit 步内未给出终局回复。"""

    def __init__(self, summary: str, user_text: str = "") -> None:
        self.summary = summary
        self.user_text = user_text
        super().__init__(summary)


def build_attempt_summary(ctx: Context, user_text: str = "", max_lines: int = 12) -> str:
    """从当前上下文提取 Captain 已尝试内容的简短摘要，供专家接手。"""
    lines: list[str] = []
    if user_text.strip():
        lines.append(f"主人任务: {user_text.strip()[:400]}")

    for m in ctx.messages[-40:]:
        if m.role == Role.ASSISTANT and m.tool_calls:
            for tc in m.tool_calls:
                name = getattr(tc, "name", None) or "?"
                lines.append(f"- 调用 {name}")
        elif m.role == Role.TOOL:
            body = (m.content or "").strip().replace("\n", " ")
            if body.startswith("[失败]"):
                lines.append(f"- 结果失败: {body[:120]}")
            elif body:
                lines.append(f"- 结果: {body[:120]}{'…' if len(body) > 120 else ''}")

    if not lines:
        return "Captain 未产生有效工具调用或终局回复。"
    tail = lines[:max_lines]
    if len(lines) > max_lines:
        tail.append(f"…(另 {len(lines) - max_lines} 条)")
    return "\n".join(tail)
