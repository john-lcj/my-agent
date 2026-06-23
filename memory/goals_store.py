"""长期目标/关注点库 —— 主动反思引擎的"它该关心什么"。

主人在这里登记长期目标与关注点(如"我在做 Captain 项目""关注 AI agent 进展"
"别让我漏了重要邮件"),引擎每次"醒来"就拿这些当判断依据,决定有没有值得主动做/提醒的事。
"""
from __future__ import annotations

import json
import os
import time
import uuid


class GoalsStore:
    def __init__(self, path: str = "logs/goals.json") -> None:
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

    def list(self) -> list[dict]:
        return self._read()

    def add(self, text: str, kind: str = "goal") -> dict:
        text = (text or "").strip()
        rows = self._read()
        # 去重:同文本不重复加
        for r in rows:
            if r.get("text") == text:
                return r
        rec = {"id": uuid.uuid4().hex[:10], "text": text,
               "kind": kind if kind in ("goal", "interest", "reminder") else "goal",
               "created_at": time.time(), "enabled": True}
        rows.append(rec)
        self._write(rows)
        return rec

    def remove(self, gid: str) -> bool:
        rows = self._read()
        new = [r for r in rows if r.get("id") != gid]
        self._write(new)
        return len(new) != len(rows)

    def active_texts(self) -> list[str]:
        return [r["text"] for r in self._read() if r.get("enabled") and r.get("text")]
