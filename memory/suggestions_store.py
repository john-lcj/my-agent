"""主动建议存储 —— agent 主动想到的事,挂这儿等主人拍板(接受/忽略)。

把"单向简报"升级成"双向商量":反思引擎想到值得做的事 → 发成一条建议
(含一句给主人看的话 + 接受后要执行的指令);主人点接受 → 指令进任务队列去做,
点忽略 → 归档。这就是"它主动想到、来问你、你点头它就做"的载体。
"""
from __future__ import annotations

import json
import os
import time
import uuid

_KINDS = ("plan", "resume", "retro", "skill", "idea")  # 规划/续做/复盘/固化技能/点子


class SuggestionsStore:
    def __init__(self, path: str = "logs/suggestions.json") -> None:
        self.path = path
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)

    def _read(self) -> list[dict]:
        if not os.path.isfile(self.path):
            return []
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def _write(self, rows: list[dict]) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def add(self, text: str, kind: str = "idea", action: str = "") -> dict:
        text = (text or "").strip()
        rows = self._read()
        # 去重:相同建议文本且还 pending 的不重复发
        for r in rows:
            if r.get("text") == text and r.get("status") == "pending":
                return r
        rec = {
            "id": uuid.uuid4().hex[:10],
            "kind": kind if kind in _KINDS else "idea",
            "text": text,
            "action": (action or "").strip(),   # 接受后要执行的指令(空=纯告知)
            "status": "pending",
            "created": time.time(),
        }
        rows.insert(0, rec)
        self._write(rows[:200])
        return rec

    def list(self, status: str = "") -> list[dict]:
        rows = self._read()
        return [r for r in rows if not status or r.get("status") == status]

    def pending(self) -> list[dict]:
        return self.list("pending")

    def set_status(self, sid: str, status: str) -> dict | None:
        rows = self._read()
        hit = None
        for r in rows:
            if r.get("id") == sid:
                r["status"] = status
                hit = r
                break
        if hit:
            self._write(rows)
        return hit
