"""Context 门面 —— 把消息日志与会话持久化从 Context 中拆出。

Context 仍是对外唯一入口;内部委托给 ConversationLog / SessionAttachment,
便于单独测试与后续扩展(多会话、共享记忆视图等)。
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Optional

from core.types import Message, Role, ToolCallRef
from memory.working import WorkingMemory


def repair_tool_pairing(messages: list[Message]) -> list[Message]:
    """按 tool_call_id 重排/补齐 tool 消息,满足 provider 严格配对协议。"""
    if not messages:
        return messages

    tools_by_id: dict[str, deque[Message]] = defaultdict(deque)
    for m in messages:
        if m.role == Role.TOOL and m.tool_call_id:
            tools_by_id[m.tool_call_id].append(m)

    out: list[Message] = []
    for m in messages:
        if m.role == Role.TOOL:
            continue
        out.append(m)
        if m.role != Role.ASSISTANT or not m.tool_calls:
            continue
        for tc in m.tool_calls:
            if not tc.id:
                continue
            if tools_by_id[tc.id]:
                out.append(tools_by_id[tc.id].popleft())
            else:
                out.append(Message(
                    role=Role.TOOL,
                    content="[系统] 工具调用未完成,已自动补齐。",
                    tool_call_id=tc.id,
                    name=tc.name,
                ))

    for q in tools_by_id.values():
        while q:
            tm = q.popleft()
            preview = (tm.content or "").strip().replace("\n", " ")[:240]
            out.append(Message(
                role=Role.USER,
                content=f"[归档的工具结果 · {tm.tool_call_id}]\n{preview}",
            ))
    return out


@dataclass
class ConversationLog:
    """对话消息追加与 LLM 视图。"""

    messages: list[Message] = field(default_factory=list)

    def add(self, message: Message) -> None:
        self.messages.append(message)

    def add_user(self, text: str) -> None:
        self.add(Message(role=Role.USER, content=text))

    def add_system(self, text: str) -> None:
        self.add(Message(role=Role.SYSTEM, content=text))

    def add_assistant(self, text: str) -> None:
        self.add(Message(role=Role.ASSISTANT, content=text))

    def add_tool_call(
        self,
        call_id: str,
        name: str,
        args: dict,
        intent: str = "",
        reasoning_content: Optional[str] = None,
    ) -> None:
        self.add(Message(
            role=Role.ASSISTANT,
            content=intent,
            tool_calls=[ToolCallRef(id=call_id, name=name, args=args)],
            reasoning_content=reasoning_content,
        ))

    def add_tool_result(self, content: str, call_id: str, name: str = "") -> None:
        self.add(Message(
            role=Role.TOOL,
            content=content,
            name=name or None,
            tool_call_id=call_id,
        ))

    def llm_view(self, working: WorkingMemory) -> list[Message]:
        self.messages = repair_tool_pairing(self.messages)
        return working.view(self.messages)


@dataclass
class SessionAttachment:
    """会话 SQLite 绑定与消息落盘。"""

    store: Optional[Any] = None
    session_id: Optional[str] = None

    def bind(self, store: Any, session_id: str, header_messages: list[Message]) -> list[Message]:
        """读回历史并 repair;返回完整 messages 列表(含 header)。"""
        self.store = store
        self.session_id = session_id
        if store is None or not session_id:
            return list(header_messages)
        if not store.session_exists(session_id):
            store.ensure_session(session_id)
        body = list(header_messages)
        for m in store.load(session_id):
            body.append(m)
        return repair_tool_pairing(body)

    def persist(self, message: Message) -> None:
        if self.store is not None and self.session_id and message.role != Role.SYSTEM:
            try:
                self.store.append(self.session_id, message)
            except Exception:
                pass
