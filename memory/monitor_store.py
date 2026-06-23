"""监控器存储 —— 盯住某个源(URL/文件),内容变化就触发一个任务。

让 agent 从"被动等指令"走向"主动感知变化即行动":后台守护按 interval 轮询每个
监控器的源,算内容指纹,与上次不同就把 action(给 Captain 的指令)投进任务队列。
"""
from __future__ import annotations

import json
import os
import time
import uuid


class MonitorStore:
    def __init__(self, path: str = "logs/monitors.json") -> None:
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

    def create(self, name: str, source_type: str, source: str, action: str,
               interval_sec: int = 1800) -> dict:
        rows = self._read()
        rec = {
            "id": uuid.uuid4().hex[:12],
            "name": name or source,
            "source_type": source_type if source_type in ("url", "file") else "url",
            "source": source,
            "action": action,
            "interval_sec": max(60, int(interval_sec or 1800)),
            "enabled": True,
            "last_hash": "",
            "last_checked": 0.0,
        }
        rows.append(rec)
        self._write(rows)
        return rec

    def delete(self, mid: str) -> bool:
        rows = self._read()
        new = [r for r in rows if r.get("id") != mid]
        self._write(new)
        return len(new) != len(rows)

    def update_state(self, mid: str, last_hash: str, last_checked: float) -> None:
        rows = self._read()
        for r in rows:
            if r.get("id") == mid:
                r["last_hash"] = last_hash
                r["last_checked"] = last_checked
                break
        self._write(rows)

    def due(self, now: float) -> list[dict]:
        """返回到检查点的、启用中的监控器。"""
        return [r for r in self._read()
                if r.get("enabled") and now - (r.get("last_checked") or 0) >= r.get("interval_sec", 1800)]
