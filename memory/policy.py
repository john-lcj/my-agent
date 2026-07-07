"""记忆策略 —— TTL、分 kind 召回、注入预算(S21/S23)。"""
from __future__ import annotations

import time
from typing import Any

# kind -> 秒; None 表示不过期
FACT_TTL: dict[str, float | None] = {
    "fact": 90 * 86400,
    "preference": None,
    "experience": 180 * 86400,
    "journal": None,
    "episode": 365 * 86400,
}

# kind -> 召回条数上限
RECALL_K: dict[str, int] = {
    "fact": 4,
    "preference": 5,
    "experience": 3,
    "episode": 2,
}

INJECT_CHAR_BUDGET = 1200


def ttl_for_kind(kind: str) -> float | None:
    return FACT_TTL.get(kind, None)


def recall_k_for_kind(kind: str) -> int:
    return RECALL_K.get(kind, 3)


def is_expired(item: Any, now: float | None = None) -> bool:
    ttl = ttl_for_kind(getattr(item, "kind", "") or "")
    if ttl is None:
        return False
    exp = getattr(item, "expires_at", None)
    if exp is not None:
        return float(exp) < (now or time.time())
    created = float(getattr(item, "created_at", 0) or 0)
    return created + ttl < (now or time.time())


def inject_with_budget(blocks: list[str], max_chars: int = 3500) -> str:
    """按顺序拼接记忆块,超出预算则截断。"""
    out: list[str] = []
    used = 0
    for b in blocks:
        b = (b or "").strip()
        if not b:
            continue
        if used + len(b) + 2 > max_chars:
            remain = max_chars - used - 20
            if remain > 80:
                out.append(b[:remain] + "…")
            break
        out.append(b)
        used += len(b) + 2
    return "\n\n".join(out)
