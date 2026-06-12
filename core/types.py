"""核心数据契约 —— 整个系统的"通用语言"。

所有层(llm / capabilities / governance / memory / agents / channels)都只依赖
这里定义的类型来互相对话。把这些定死,各层才能独立演进、独立替换。

设计原则:
- 这里只放"数据"和"枚举",不放任何业务逻辑。
- 字段尽量为未来留好位置(如 trace_id、actor),签名一次定对,避免后期大改。
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class Role(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    SYSTEM = "system"


class Risk(int, Enum):
    """能力的风险等级。治理层据此决定放行/询问/拒绝。

    顺序有意义:数值越大越危险,便于比较(如 risk >= DESTRUCTIVE)。
    """
    READ = 1          # 读文件、搜索、查询 —— 永不打扰
    WRITE = 2         # 改文件、写新文件 —— 默认询问,可授权放手
    DESTRUCTIVE = 3   # 删除、覆盖、危险命令、花钱、GUI 控制 —— 总是询问
    FORBIDDEN = 4     # .env / rm -rf / force push main —— 代码层直接拒绝


class Decision(str, Enum):
    """治理层对一次能力调用的裁决。"""
    ALLOW = "allow"
    ASK = "ask"
    BLOCK = "block"


@dataclass
class GovReview:
    """一次治理裁决的完整结果 —— 不只给"判罚",还给"为什么"和"哪条规则"。

    这让"拒绝"从一堵沉默的墙,变成一次可解释、可审计、可迭代的沟通:
    - reason:回传给模型与用户,解释为何这么裁决;
    - rule:命中的规则标识,落进 trace 后可统计"哪条规则最常触发"。
    """
    decision: Decision
    reason: str = ""
    rule: str = ""


@dataclass
class Identity:
    """动作的"主体":谁让做的、哪个 agent 在做。

    单 agent 阶段几乎用不到,但治理签名从第一天就带上它,
    为多 agent / 外部 channel 的"按主体鉴权"预留。
    """
    subject_id: str = "local-user"     # 外部用户/调用方
    agent_name: str = "main"           # 执行该动作的 agent
    channel: str = "cli"               # 消息来源渠道
    roles: tuple[str, ...] = ()        # 主体拥有的角色(用于权限白名单)


@dataclass
class ToolCallRef:
    """assistant 发起的一次工具调用的引用。

    id 用于把"调用"与"结果"严格配对(OpenAI 的 tool_call_id / Anthropic 的 tool_use id),
    保证多轮工具链路的对话记录合法且可被模型正确理解。
    """
    id: str
    name: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass
class Message:
    role: Role
    content: str
    # 可选:工具调用产生的消息可携带其结果,便于审计与回放
    name: Optional[str] = None
    # assistant 消息:本轮发起的工具调用(可多个)。
    tool_calls: list[ToolCallRef] = field(default_factory=list)
    # tool 消息:对应的工具调用 id(与某个 ToolCallRef.id 配对)。
    tool_call_id: Optional[str] = None
    # DeepSeek 思考模式:带 tool_calls 的 assistant 轮次必须原样回传。
    reasoning_content: Optional[str] = None
    ts: float = field(default_factory=time.time)


@dataclass
class CapabilityCall:
    """agent 想"做一件事"的统一表示。

    无论是调工具、跑 skill、控制 GUI,还是委托另一个 agent,
    都收敛成这一种调用对象,统一过治理管线。
    """
    name: str                          # 能力标识,如 "fs.write" / "skill.search"
    args: dict[str, Any] = field(default_factory=dict)
    intent: str = ""                   # 模型声明"我为什么要这么做"(把诚实工程化)
    declared_risk: Optional[Risk] = None  # 模型对自身动作的风险自评(供治理核对)
    call_id: str = ""                  # provider 返回的工具调用 id,用于结果配对


@dataclass
class Step:
    """LLM 每一轮的输出:要么直接回话,要么发起一次能力调用。"""
    text: Optional[str] = None
    call: Optional[CapabilityCall] = None
    reasoning_content: Optional[str] = None

    @property
    def is_final(self) -> bool:
        return self.call is None


@dataclass
class CapabilityResult:
    """一次能力执行的结果。"""
    ok: bool
    output: str = ""
    error: Optional[str] = None


# 历史别名:工具结果就是能力结果的一种,保留以便阅读直觉。
ToolResult = CapabilityResult


class EventType(str, Enum):
    """事件总线上的事件类型。多 agent / 多 channel / 流式都靠事件驱动。"""
    USER_MESSAGE = "user_message"
    ASSISTANT_TOKEN = "assistant_token"   # 流式 token
    ASSISTANT_MESSAGE = "assistant_message"
    CAPABILITY_CALL = "capability_call"
    CAPABILITY_RESULT = "capability_result"
    APPROVAL_REQUEST = "approval_request"  # 软边界:请求用户确认
    APPROVAL_RESULT = "approval_result"
    GOVERNANCE_DECISION = "governance_decision"  # 治理裁决(含命中规则+原因),供审计与统计
    TASK_DONE = "task_done"
    STATUS_BAR = "status_bar"           # 输入框上方状态栏(模型/上下文/时长)
    ERROR = "error"


@dataclass
class Event:
    """总线上流动的一条事件。

    trace_id 从一开始就带上,为多 agent 的分布式链路追踪预留:
    一个任务跨多个 agent / 工具,可凭 trace_id 串成一条完整链路。
    """
    type: EventType
    payload: dict[str, Any] = field(default_factory=dict)
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    ts: float = field(default_factory=time.time)
