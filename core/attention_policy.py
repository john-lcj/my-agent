"""Phase 7 attention decisions for proactive work.

This controls interruption channel, not execution authority.  A policy may
reduce a notification to silent logging, but it can never turn missing
authority into an automatic external action.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AttentionAction(str, Enum):
    SILENT = "silent"
    IN_APP = "in_app"
    EMAIL = "email"
    CONFIRM = "confirm"
    STOP = "stop"


@dataclass(frozen=True)
class AttentionDecision:
    action: AttentionAction
    reason: str
    consumes_interruption: bool = False


def decide_attention(
    *,
    urgency: str = "normal",
    impact: str = "low",
    authority_granted: bool = False,
    interruption_count: int = 0,
    interruption_budget: int = 3,
    requires_confirmation: bool = False,
) -> AttentionDecision:
    urgency = (urgency or "normal").lower()
    impact = (impact or "low").lower()
    if not authority_granted and impact in {"high", "critical"}:
        return AttentionDecision(AttentionAction.STOP, "high-impact action lacks stored authority")
    if requires_confirmation:
        return AttentionDecision(AttentionAction.CONFIRM, "action requires owner confirmation", True)
    if urgency == "low":
        return AttentionDecision(AttentionAction.SILENT, "low urgency is logged without interruption")
    if interruption_count >= max(0, interruption_budget) and urgency != "urgent":
        return AttentionDecision(AttentionAction.SILENT, "interruption budget is exhausted")
    if urgency == "urgent" or impact == "critical":
        return AttentionDecision(AttentionAction.EMAIL, "urgent or critical item needs timely owner attention", True)
    return AttentionDecision(AttentionAction.IN_APP, "material change can wait for an in-app notification", True)
