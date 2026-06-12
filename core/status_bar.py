"""会话状态栏 —— 模型 / 上下文 / 会话时长 / 上次耗时。"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional

from governance.budget import _count_tokens
from llm.model_registry import get_model


def model_display_name(model_id: str) -> str:
    return get_model(model_id).id


def context_window_size(model_id: str) -> int:
    return get_model(model_id).context


def format_tokens_short(n: int) -> str:
    n = max(0, int(n))
    if n >= 1_000_000:
        v = n / 1_000_000
        return f"{v:.1f}M".replace(".0M", "M")
    if n >= 1000:
        v = n / 1000
        s = f"{v:.1f}K"
        return s.replace(".0K", "K")
    return str(n)


def format_duration(seconds: float) -> str:
    s = max(0, int(seconds))
    if s < 60:
        return f"{s}s"
    m, sec = divmod(s, 60)
    if m < 60:
        return f"{m}m {sec}s" if sec else f"{m}m"
    h, m = divmod(m, 60)
    return f"{h}h {m}m"


def progress_bar(pct: float, width: int = 10) -> str:
    pct = max(0.0, min(100.0, float(pct)))
    filled = int(round(pct * width / 100))
    filled = min(width, max(0, filled))
    return "[" + ("█" * filled) + ("░" * (width - filled)) + "]"


def estimate_context_tokens(ctx: Any, model_id: str) -> int:
    try:
        spec = get_model(model_id)
        parts = []
        for m in ctx.llm_view():
            parts.append(getattr(m, "content", "") or "")
            tcs = getattr(m, "tool_calls", None) or []
            for tc in tcs:
                parts.append(str(getattr(tc, "args", "")))
        text = "\n".join(parts)
        return _count_tokens(text, spec.provider)
    except Exception:
        return 0


@dataclass
class StatusSnapshot:
    model: str
    provider: str
    tokens_used: int
    context_size: int
    pct: float
    session_seconds: float
    last_task_seconds: Optional[float] = None

    def to_payload(self) -> dict:
        return {
            "model": self.model,
            "provider": self.provider,
            "tokens_used": self.tokens_used,
            "context_size": self.context_size,
            "tokens_label": f"{format_tokens_short(self.tokens_used)}/{format_tokens_short(self.context_size)}",
            "pct": round(self.pct, 1),
            "bar": progress_bar(self.pct),
            "session_label": format_duration(self.session_seconds),
            "last_task_label": format_duration(self.last_task_seconds or 0) if self.last_task_seconds is not None else "—",
            "line": format_status_line(self),
        }


def build_status_snapshot(
    *,
    model_id: str,
    ctx: Any,
    budget: Any = None,
    session_started_at: float,
    last_task_seconds: Optional[float] = None,
) -> StatusSnapshot:
    spec = get_model(model_id)
    ctx_size = spec.context
    used = estimate_context_tokens(ctx, model_id)
    if budget is not None:
        used = max(used, int(getattr(budget, "tokens", 0) or 0))
    pct = (used / ctx_size * 100) if ctx_size else 0.0
    return StatusSnapshot(
        model=spec.id,
        provider=spec.provider,
        tokens_used=used,
        context_size=ctx_size,
        pct=pct,
        session_seconds=time.time() - session_started_at,
        last_task_seconds=last_task_seconds,
    )


def format_status_line(s: StatusSnapshot) -> str:
    tok = f"{format_tokens_short(s.tokens_used)}/{format_tokens_short(s.context_size)}"
    return f"{tok} │ {progress_bar(s.pct)} {int(round(s.pct))}%"


def emit_status_event(channel, agent, ctx, model_id: str, session_started_at: float, last_task_seconds=None) -> StatusSnapshot:
    from core.types import Event, EventType
    snap = build_status_snapshot(
        model_id=model_id,
        ctx=ctx,
        budget=getattr(agent, "budget", None),
        session_started_at=session_started_at,
        last_task_seconds=last_task_seconds,
    )
    if channel is not None and hasattr(channel, "emit"):
        channel.emit(Event(type=EventType.STATUS_BAR, payload=snap.to_payload()))
    return snap
