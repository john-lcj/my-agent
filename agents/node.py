"""ChatAgent —— 一个"会发言"的 agent 节点。

它读取共享讨论记录,以自己的角色身份贡献一段观点。多个 ChatAgent 由编排策略
(流水线 / 圆桌 / 辩论)组织起来协同。为保持 provider 友好且确定可测,
这里以纯文本对话方式发言(不直接调工具)。
"""
from __future__ import annotations

from core.types import Message, Role


class ChatAgent:
    def __init__(self, name: str, role: str, llm, system_prompt: str = "") -> None:
        self.name = name
        self.role = role
        self.llm = llm
        self.system_prompt = system_prompt or f"你在一个多方讨论中扮演「{role}」。发言简短、聚焦、对事不对人。"

    async def step(self, task: str, conversation: list[Message]) -> Message:
        transcript = "\n".join(f"{m.name or m.role.value}: {m.content}" for m in conversation)
        prompt = (
            f"议题:{task}\n\n"
            f"目前的讨论记录:\n{transcript or '(还没有人发言)'}\n\n"
            f"你是「{self.role}」,请发表你的下一条观点(简短)。"
        )
        messages = [
            Message(role=Role.SYSTEM, content=self.system_prompt),
            Message(role=Role.USER, content=prompt),
        ]
        step = await self.llm.next_step(messages, [])
        return Message(role=Role.ASSISTANT, content=step.text or "", name=self.name)
