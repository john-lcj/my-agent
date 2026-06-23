"""主动建议能力 —— 让(反思中的)agent 把想到的事发给主人拍板。

suggest.add:发一条建议(一句话 + 接受后要执行的指令)。
suggest.list:看现有待处理建议(避免重复发)。
"""
from __future__ import annotations

from typing import Any

from capabilities.tools.base import Tool
from core.types import CapabilityResult, Risk


def _store(ctx: Any):
    return getattr(ctx, "suggestions", None)


class SuggestAdd(Tool):
    name = "suggest.add"
    risk = Risk.READ   # 只是挂一条待办建议给主人看,不直接产生副作用
    description = (
        "把你主动想到、值得做的事发成一条建议给主人拍板(他接受才会执行)。"
        "kind:plan(今天做什么)/resume(续做没完成的)/retro(复盘)/skill(固化成技能)/idea(点子)。"
        "action 写「接受后该执行的具体指令」(纯告知/复盘可留空)。")
    schema = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "给主人看的一句话(说清是什么、为什么值得做)"},
            "kind": {"type": "string", "description": "plan/resume/retro/skill/idea"},
            "action": {"type": "string", "description": "主人点「接受」后要执行的指令(可空)"},
        },
        "required": ["text"],
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        st = _store(ctx)
        if st is None:
            return CapabilityResult(ok=False, error="未配置建议存储")
        text = str(args.get("text", "")).strip()
        if not text:
            return CapabilityResult(ok=False, error="缺少 text")
        rec = st.add(text, str(args.get("kind", "idea")), str(args.get("action", "")))
        return CapabilityResult(ok=True, output=f"已向主人发出建议:{rec['text']}")


class SuggestList(Tool):
    name = "suggest.list"
    risk = Risk.READ
    description = "列出当前待主人处理的主动建议(避免重复发同样的)。"
    schema = {"type": "object", "properties": {}}

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        st = _store(ctx)
        if st is None:
            return CapabilityResult(ok=False, error="未配置建议存储")
        rows = st.pending()
        if not rows:
            return CapabilityResult(ok=True, output="(暂无待处理建议)")
        return CapabilityResult(ok=True, output="\n".join(
            f"- [{r['kind']}] {r['text']}" for r in rows))
