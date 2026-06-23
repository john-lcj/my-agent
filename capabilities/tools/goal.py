"""长期目标能力 —— 让主人(或 agent)登记/查看主动性引擎要关心的目标与关注点。"""
from __future__ import annotations

from typing import Any

from capabilities.tools.base import Tool
from core.types import CapabilityResult, Risk


def _store(ctx: Any):
    return getattr(ctx, "goals", None)


class GoalSet(Tool):
    name = "goal.set"
    risk = Risk.WRITE
    description = ("登记一条长期目标/关注点,主动反思引擎会持续据此判断有没有值得主动做或提醒的事。"
                  "如『我在做 Captain 项目』『关注 AI agent 领域进展』『别让我漏了重要邮件』。")
    schema = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "目标或关注点的一句话描述"},
            "kind": {"type": "string", "description": "goal(目标)/interest(关注)/reminder(提醒),默认 goal"},
        },
        "required": ["text"],
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        st = _store(ctx)
        if st is None:
            return CapabilityResult(ok=False, error="未配置目标库")
        text = str(args.get("text", "")).strip()
        if not text:
            return CapabilityResult(ok=False, error="缺少 text")
        rec = st.add(text, str(args.get("kind", "goal")))
        return CapabilityResult(ok=True, output=f"已登记长期目标:{rec['text']}")


class GoalList(Tool):
    name = "goal.list"
    risk = Risk.READ
    description = "列出主人已登记的长期目标/关注点。"
    schema = {"type": "object", "properties": {}}

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        st = _store(ctx)
        if st is None:
            return CapabilityResult(ok=False, error="未配置目标库")
        rows = st.list()
        if not rows:
            return CapabilityResult(ok=True, output="(还没有登记长期目标)")
        return CapabilityResult(ok=True, output="\n".join(
            f"- [{r['id']}|{r.get('kind','goal')}] {r['text']}" for r in rows))


class GoalRemove(Tool):
    name = "goal.remove"
    risk = Risk.WRITE
    description = "按 id 删除一条长期目标。"
    schema = {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        st = _store(ctx)
        if st is None:
            return CapabilityResult(ok=False, error="未配置目标库")
        ok = st.remove(str(args.get("id", "")).strip())
        return CapabilityResult(ok=ok, output="已删除" if ok else "未找到该目标")
