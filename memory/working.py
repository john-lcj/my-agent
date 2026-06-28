"""工作记忆 —— 上下文工程的核心:摘要压缩(summarization buffer)。

产品级 agent 的"长对话不失忆",主要靠这个,而不是向量库:
当对话超出预算,把较早的消息压缩成一条摘要,替换掉原文,只保留摘要 + 最近若干轮。

关键安全约束:压缩的切点必须落在"用户消息边界"上,绝不能把一次
assistant 工具调用与其 tool 结果拆散(否则破坏严格配对协议)。

本类只提供"何时压缩 / 怎么切分"的策略;真正的摘要由外部注入的 summarizer
(通常是一个便宜模型)异步完成,见 Context.compact。
"""
from __future__ import annotations

from core.types import Message, Role


class WorkingMemory:
    def __init__(self, max_chars: int = 6000, keep_recent: int = 10) -> None:
        self.max_chars = max_chars
        self.keep_recent = keep_recent

    def view(self, messages: list[Message]) -> list[Message]:
        """喂给 LLM 的消息视图。压缩已由 Context.compact 永久完成,这里原样返回。"""
        return messages

    def should_compact(self, messages: list[Message]) -> bool:
        return sum(len(m.content) for m in messages) > self.max_chars

    def partition(self, messages: list[Message]):
        """切分为 (header, older, recent)。

        - header:开头连续的系统消息(系统提示词 + 既有摘要),始终保留。
        - older:需要被摘要压缩的早期消息。
        - recent:保留原文的近期消息,从某个"用户消息边界"开始。
        若找不到安全切点,older 为空(不压缩)。
        """
        i = 0
        while i < len(messages) and messages[i].role == Role.SYSTEM:
            i += 1
        header = messages[:i]
        body = messages[i:]

        if len(body) <= self.keep_recent:
            return header, [], body

        cut = len(body) - self.keep_recent
        # 把切点后移到最近的"用户消息边界"(<= cut),保证 recent 以 USER 开头,
        # 不会把某次 assistant 工具调用与其 tool 结果拆散。
        while cut > 0 and body[cut].role != Role.USER:
            cut -= 1
        if cut <= 0:
            return header, [], body
        recent = body[cut:]
        # recent 不得以孤立的 tool 开头(否则摘要后 assistant 与 tool 被拆开)
        while recent and recent[0].role == Role.TOOL and cut > 0:
            cut -= 1
            recent = body[cut:]
        while cut > 0 and recent and recent[0].role != Role.USER:
            cut -= 1
            if cut <= 0:
                return header, [], body
            recent = body[cut:]
        return header, body[:cut], recent
