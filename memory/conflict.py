"""偏好冲突检测 —— 新写入前提示覆盖/并存。"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

# 同主题高相似(但不相同)的旧偏好视为被新偏好取代,如「用英文回复」→「用中文回复」。
_SIMILARITY_SUPERSEDE = 0.72


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", (s or "").lower())


def is_superseding(new_content: str, old_content: str) -> bool:
    """新偏好是否应取代旧偏好:同主题(高字面相似)但内容不同。"""
    a, b = _norm(new_content), _norm(old_content)
    if not a or not b or a == b:
        return False
    # 互为子串是"细化/重复",交给去重处理,不算冲突
    if a in b or b in a:
        return False
    return SequenceMatcher(None, a, b).ratio() >= _SIMILARITY_SUPERSEDE


def detect_preference_conflict(existing: list[Any], new_content: str) -> str | None:
    text = (new_content or "").strip()
    if not text:
        return None
    pairs = [
        ("喜欢", "不喜欢"),
        ("偏好", "不偏好"),
        ("要", "不要"),
        ("开启", "关闭"),
        ("用", "不用"),
    ]
    for a, b in pairs:
        if a in text and b not in text:
            for item in existing:
                c = getattr(item, "content", None) or (item.get("content") if isinstance(item, dict) else "")
                if not c:
                    continue
                if b in c and (_norm(a) in _norm(c) or (a in c and b in text)):
                    return f"与已有偏好可能冲突: {c[:80]}"
    return None


def resolve_preference_conflict(longterm, new_content: str, scope: str = "") -> None:
    """同 scope 下删除与新偏好明显冲突的旧条(反义词对 或 同主题高相似),并记审计。"""
    try:
        rows = longterm.list_by_kind("preference", limit=200)
    except Exception:
        return
    scoped = [r for r in rows if not scope or r.get("scope", "") in ("", scope)]
    superseded: list[str] = []
    for r in scoped:
        old = r.get("content") or ""
        if not old:
            continue
        if is_superseding(new_content, old) or detect_preference_conflict(
            [{"content": new_content}], old,
        ):
            longterm.delete_by_content("preference", old)
            superseded.append(old)
    if not superseded:
        return
    try:
        from observability.audit import audit
        audit(capability="memory.preference_conflict", decision="supersede",
              detail=f"新偏好取代 {len(superseded)} 条旧偏好: {superseded[0][:60]}", ok=True)
    except Exception:
        pass
