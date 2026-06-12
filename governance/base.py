"""治理层接口 —— "分寸感"的物理位置。

设计要点:从第一天就用三参数签名 review(call, actor, ctx):
- call:要做什么(统一的 CapabilityCall)
- actor:谁让做的 / 哪个 agent 在做(Identity)—— 为多 agent/多用户的按主体鉴权预留
- ctx:当前会话上下文(含授权 grants、预算等)

安全必须由确定性的代码保证,绝不写在 prompt 里。
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from core.types import CapabilityCall, Decision, GovReview, Identity


@runtime_checkable
class PolicyEngine(Protocol):
    def review(self, call: CapabilityCall, actor: Identity, ctx: Any) -> Decision:
        ...

    def review_detailed(self, call: CapabilityCall, actor: Identity, ctx: Any) -> GovReview:
        ...
