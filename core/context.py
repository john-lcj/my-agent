"""会话上下文 —— 对外统一入口,内部委托 ConversationLog / SessionAttachment。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from core.context_facade import ConversationLog, SessionAttachment, repair_tool_pairing
from core.types import Identity, Message, Role
from memory.working import WorkingMemory

# 向后兼容:其它模块 continue `from core.context import repair_tool_pairing`
__all__ = ["Context", "repair_tool_pairing", "ConversationLog", "SessionAttachment"]


@dataclass
class Context:
    identity: Identity = field(default_factory=Identity)
    grants: set[str] = field(default_factory=set)
    # 本会话内按能力名前缀放手(如 fs.write / shell.run)
    capability_grants: set[str] = field(default_factory=set)
    # 当前用户问题内:点过一次「允许」后,后续 ASK 不再弹窗
    task_auto_approve: bool = False
    # Captain 汇总轮(显式 /专家名 后):避免 Coordinator 二次路由
    captain_only: bool = False
    # Coworker 引擎:极致工作模式 —— 非闲聊任务一律强制走 DAG 编排、激进派子代理
    coworker: bool = False
    working: WorkingMemory = field(default_factory=WorkingMemory)
    log: ConversationLog = field(default_factory=ConversationLog)
    session: SessionAttachment = field(default_factory=SessionAttachment)
    longterm: Optional[Any] = None
    program: Optional[Any] = None

    @property
    def messages(self) -> list[Message]:
        return self.log.messages

    @messages.setter
    def messages(self, value: list[Message]) -> None:
        self.log.messages = value

    @property
    def store(self) -> Optional[Any]:
        return self.session.store

    @store.setter
    def store(self, value: Optional[Any]) -> None:
        self.session.store = value

    @property
    def session_id(self) -> Optional[str]:
        return self.session.session_id

    @session_id.setter
    def session_id(self, value: Optional[str]) -> None:
        self.session.session_id = value

    def bind_session(self, store: Any, session_id: str, *, create: bool = False) -> None:
        self.session.store = store
        self.session.session_id = session_id
        if store is None or not session_id:
            return
        if create:
            store.ensure_session(session_id)
        elif not store.session_exists(session_id):
            return
        for m in store.load(session_id):
            self.log.messages.append(m)
        self.log.messages = repair_tool_pairing(self.log.messages)

    def add(self, message: Message) -> None:
        self.log.add(message)
        self.session.persist(message)

    def add_user(self, text: str) -> None:
        self.add(Message(role=Role.USER, content=text))

    def add_system(self, text: str) -> None:
        self.add(Message(role=Role.SYSTEM, content=text))

    def add_assistant(self, text: str, *, name: str | None = None) -> None:
        self.add(Message(role=Role.ASSISTANT, content=text, name=name))

    def add_tool_call(
        self,
        call_id: str,
        name: str,
        args: dict,
        intent: str = "",
        reasoning_content: Optional[str] = None,
    ) -> None:
        self.log.add_tool_call(
            call_id, name, args, intent, reasoning_content=reasoning_content,
        )
        self.session.persist(self.log.messages[-1])

    def add_tool_result(self, content: str, call_id: str, name: str = "") -> None:
        self.log.add_tool_result(content, call_id, name)
        self.session.persist(self.log.messages[-1])

    def llm_view(self) -> list[Message]:
        return self.log.llm_view(self.working)

    async def compact(self, summarizer) -> bool:
        if summarizer is None or not self.working.should_compact(self.messages):
            return False
        header, older, recent = self.working.partition(self.messages)
        if not older:
            return False
        rendered = "\n".join(f"{m.role.value}: {m.content}" for m in older if m.content)
        try:
            summary = await summarizer(rendered)
        except Exception:
            return False
        self.messages = repair_tool_pairing(list(header) + [
            Message(role=Role.SYSTEM, content=f"[早期对话摘要]\n{summary}")
        ] + list(recent))
        return True

    def grant(self, path: str) -> None:
        if path:
            self.grants.add(path)

    def is_granted(self, path: str) -> bool:
        if not path:
            return False
        return any(path == g or path.startswith(g.rstrip("/") + "/") for g in self.grants)

    def grant_capability(self, prefix: str) -> None:
        p = (prefix or "").strip()
        if p:
            self.capability_grants.add(p)

    def is_capability_granted(self, name: str) -> bool:
        if not name:
            return False
        return any(name == g or name.startswith(g) for g in self.capability_grants)
