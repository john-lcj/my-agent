"""可读 transcript —— 把一次 run 的全过程写成人能读的 Markdown,供"读 transcript 迭代"。

这是"把核心回路做深"的诊断仪表:每轮跑完,logs/transcripts/<trace>.md 里能清楚看到
用户说了什么 → 模型每一步的意图/调了什么工具/参数/结果 → 治理决策 → 最终回复。
失败静默,绝不拖垮主流程。
"""
from __future__ import annotations

import json
import os
import time


class Transcript:
    def __init__(self, trace_id: str, base_dir: str | None = None) -> None:
        base = base_dir or os.path.join(
            os.environ.get("AGENT_LOG_DIR", "").strip() or "logs", "transcripts")
        self.path = ""
        try:
            os.makedirs(base, exist_ok=True)
            self.path = os.path.join(base, f"{trace_id}.md")
        except Exception:
            self.path = ""
        self._step = 0

    def _w(self, text: str) -> None:
        if not self.path:
            return
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(text + "\n")
        except Exception:
            pass

    def start(self, user_text: str, coworker: bool) -> None:
        mode = "Cowork" if coworker else "Chat"
        self._w(f"# Run @ {time.strftime('%Y-%m-%d %H:%M:%S')}  ·  {mode}\n")
        self._w(f"**用户**:{user_text}\n")

    def call(self, name: str, intent: str, args: dict) -> None:
        self._step += 1
        try:
            a = json.dumps(args, ensure_ascii=False)[:500]
        except Exception:
            a = str(args)[:500]
        self._w(f"## 步骤 {self._step} · 调用 `{name}`")
        if intent:
            self._w(f"- 意图:{intent}")
        self._w(f"- 参数:`{a}`")

    def decision(self, decision: str, reason: str) -> None:
        if decision and decision != "allow":
            self._w(f"- 治理:**{decision}** {reason}".rstrip())

    def result(self, ok: bool, output: str, error: str) -> None:
        body = (output if ok else f"[失败] {error}") or ""
        self._w(f"- 结果:{'✅' if ok else '❌'} {body[:600]}\n")

    def note(self, text: str) -> None:
        self._w(f"> ⚠ {text}\n")

    def final(self, text: str) -> None:
        self._w(f"## 最终回复\n\n{(text or '')[:2000]}\n")
