"""从 policy.yaml 生成治理说明(供 API/前端展示)。"""
from __future__ import annotations

import os
from typing import Any


def load_policy_summary(policy_path: str | None = None) -> dict[str, Any]:
    path = policy_path or os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "governance", "policy.yaml",
    )
    if not os.path.isfile(path):
        return {"block": [], "confirm": [], "auto": []}
    try:
        import yaml
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        return {"block": [], "confirm": [], "auto": []}

    block: list[dict] = []
    for item in (data.get("forbidden_patterns") or []):
        block.append({"kind": "pattern", "rule": item.get("pattern", ""), "reason": item.get("reason", "")})
    for item in (data.get("forbidden_paths") or []):
        block.append({"kind": "path", "rule": item.get("pattern", ""), "reason": item.get("reason", "")})

    confirm_caps = list((data.get("confirm") or {}).get("capabilities") or [])
    confirm = [{"capability": c, "reason": "执行前需主人确认"} for c in confirm_caps]

    auto_samples = [
        "fs.read", "fs.list", "memory.remember", "memory.recall",
        "web.search", "web.fetch",
    ]
    auto = [{"capability": c, "reason": "只读或低风险,默认放行"} for c in auto_samples]
    return {"block": block, "confirm": confirm, "auto": auto}
