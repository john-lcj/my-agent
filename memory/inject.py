"""开场记忆注入 —— journal + experience + recall 统一预算(S23)。"""
from __future__ import annotations

from typing import Any

from memory.policy import INJECT_CHAR_BUDGET, inject_with_budget, recall_k_for_kind


def build_opening_memory_block(ctx: Any, user_text: str) -> str:
    """合并长期记忆/经验/协作简报,按相关性排序后截断到预算内。"""
    mem = getattr(ctx, "longterm", None)
    blocks: list[str] = []

    try:
        from memory.journal import Journal
        from config import Config
        jpath = f"{Config.LOG_DIR}/journal.md"
        snippet = Journal(path=jpath).render_briefing(1) if hasattr(Journal, "render_briefing") else ""
        if snippet and snippet.strip() and "(暂无" not in snippet:
            blocks.append("[上次协作进度 · 供续接]\n" + snippet.strip())
    except Exception:
        pass

    if mem is not None:
        try:
            from memory.experience_miner import format_experience_block
            exp = format_experience_block(mem, user_text, k=recall_k_for_kind("experience"))
            if exp:
                blocks.append(exp)
        except Exception:
            pass

        try:
            _scope = getattr(ctx, "mem_scope", None)
            if _scope is None:
                _ch = getattr(getattr(ctx, "identity", None), "channel", "") or ""
                _scope = f"{_ch}|" if _ch else None
            k = recall_k_for_kind("fact") + recall_k_for_kind("preference")
            items = mem.retrieve(user_text, k=max(3, k), scope=_scope)
        except Exception:
            items = []
        if items:
            src_label = {"user": "用户", "agent": "推断"}
            lines = []
            for it in items:
                stale = getattr(it, "stale", False)
                tag = "需刷新·" if stale else ""
                lines.append(
                    f"- {tag}[{it.kind}|{src_label.get(it.source, it.source)}] {it.content}",
                )
            blocks.append("[关于主人的已知记忆,供参考]\n" + "\n".join(lines))

    if not blocks:
        return ""
    return inject_with_budget(blocks, max_chars=INJECT_CHAR_BUDGET)
