"""FileTracer —— 把每个事件追加为一行 JSON(JSONL),便于审计与回放。

可选地在控制台打印精简事件,方便开发期观察 agent 在干什么。
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict

from core.types import Event, EventType
from observability.log_rotation import append_text


class FileTracer:
    def __init__(self, log_dir: str = "logs", echo: bool = False) -> None:
        os.makedirs(log_dir, exist_ok=True)
        self.path = os.path.join(log_dir, "trace.jsonl")
        self.echo = echo

    def log(self, event: Event) -> None:
        record = {
            "ts": event.ts,
            "trace_id": event.trace_id,
            "type": event.type.value,
            "payload": _safe(event.payload),
        }
        append_text(self.path, json.dumps(record, ensure_ascii=False) + "\n")
        if self.echo and event.type != EventType.ASSISTANT_TOKEN:
            # token 已由 Channel 流式展示,再 echo 会重复刷屏
            print(f"  · trace[{event.type.value}] {record['payload']}")


def _safe(payload: dict) -> dict:
    out = {}
    for k, v in payload.items():
        try:
            json.dumps(v, ensure_ascii=False)
            out[k] = v
        except TypeError:
            try:
                out[k] = asdict(v)
            except Exception:
                out[k] = str(v)
    return out
