"""行动分级 —— 把一次能力调用映射到权威的风险等级。

关键原则:风险以"能力自报的 risk"为权威来源(注册在代码里),
不信任模型的自评(declared_risk 仅用于核对/审计)。未知能力按 fail-safe
处理为高危,宁可多问一次。
"""
from __future__ import annotations

from core.types import CapabilityCall, Risk


def classify(call: CapabilityCall, registry) -> Risk:
    cap = registry.get(call.name) if registry is not None else None
    manifest = registry.manifest_for(call.name) if cap is not None else None
    if manifest is not None:
        return manifest.risk
    # The model-declared risk is untrusted metadata. Missing or incomplete
    # capability metadata is never executable.
    return Risk.FORBIDDEN
