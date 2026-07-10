"""Shared governed invocation for non-loop capability entry points."""
from __future__ import annotations

from typing import Awaitable, Callable

from core.types import CapabilityCall, CapabilityResult, Decision, Identity

ConfirmFn = Callable[[CapabilityCall, Decision, str], Awaitable[bool]]


async def invoke_governed(
    registry,
    policy,
    call: CapabilityCall,
    actor: Identity,
    ctx,
    confirm: ConfirmFn | None = None,
) -> CapabilityResult:
    """Review and invoke a capability without creating a policy bypass."""
    review = policy.review_detailed(call, actor, ctx)
    if review.decision == Decision.BLOCK:
        return CapabilityResult(
            ok=False,
            error=f"capability blocked: {review.reason}",
        )
    if review.decision == Decision.ASK:
        if confirm is None or not await confirm(call, review.decision, review.reason):
            return CapabilityResult(ok=False, error="capability approval was not granted")
    return await registry.invoke(call.name, call.args, ctx)
