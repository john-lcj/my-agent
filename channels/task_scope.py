"""Web 会话任务代际 —— 防止取消中的旧任务事件污染 UI。"""
from __future__ import annotations

import contextvars

_task_gen: contextvars.ContextVar[int] = contextvars.ContextVar("task_gen", default=0)


def current_task_gen() -> int:
    return _task_gen.get()


def set_task_gen(gen: int):
    return _task_gen.set(gen)


def reset_task_gen(token) -> None:
    _task_gen.reset(token)
