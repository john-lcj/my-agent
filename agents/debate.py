"""辩论编排 —— 正反方交替发言,最后由主持人总结。

事件(经 on_event 推送,与圆桌类似):
  debate_message  {side, name, content, round}
  debate_summary  {content}
  debate_done     {rounds, stopped}
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional

from agents.node import ChatAgent
from core.types import Message, Role

OnEvent = Callable[[dict], Awaitable[None]]


class Debate:
    def __init__(self, llm_factory: Callable[[str], Any], max_rounds: int = 3) -> None:
        self._llm_factory = llm_factory
        self.max_rounds = max_rounds

    async def run(
        self,
        topic: str,
        *,
        pro_model: str = "mock",
        con_model: str = "mock",
        moderator_model: str = "mock",
        on_event: Optional[OnEvent] = None,
    ) -> dict:
        async def emit(evt: dict) -> None:
            if on_event is not None:
                await on_event(evt)

        pro = ChatAgent(
            "正方",
            "正方辩手",
            self._llm_factory(pro_model),
            "你支持该议题。用简短有力的论据发言,直接回应反方观点。",
        )
        con = ChatAgent(
            "反方",
            "反方辩手",
            self._llm_factory(con_model),
            "你反对该议题。指出正方漏洞,提出替代方案或风险。",
        )
        transcript: list[Message] = []
        rounds = 0

        for r in range(1, self.max_rounds + 1):
            rounds = r
            pm = await pro.step(topic, transcript)
            transcript.append(pm)
            await emit({
                "type": "debate_message",
                "side": "pro",
                "name": pro.name,
                "content": pm.content,
                "round": r,
            })
            cm = await con.step(topic, transcript)
            transcript.append(cm)
            await emit({
                "type": "debate_message",
                "side": "con",
                "name": con.name,
                "content": cm.content,
                "round": r,
            })

        lines = "\n".join(
            f"[{m.name or m.role.value}] {m.content}" for m in transcript if m.content)
        mod = self._llm_factory(moderator_model)
        prompt = (
            f"议题:{topic}\n\n辩论记录:\n{lines or '(无)'}\n\n"
            "你是主持人,请用简体中文给出中立总结:双方核心论点、共识与分歧、建议下一步(200字内)。"
        )
        step = await mod.next_step([
            Message(role=Role.SYSTEM, content="你是辩论主持人,只输出总结,不站队。"),
            Message(role=Role.USER, content=prompt),
        ], [])
        summary = step.text or lines
        await emit({"type": "debate_summary", "content": summary})
        await emit({"type": "debate_done", "rounds": rounds, "stopped": "completed"})
        return {"transcript": transcript, "summary": summary, "rounds": rounds}
