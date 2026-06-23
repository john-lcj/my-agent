"""长任务断点 —— 把每轮的待办清单进度落盘,会话中断后可续跑。

plan.update 一更新,就把当前待办快照存到 logs/checkpoints/<session>.json。
重开同一会话时,server 把"还没做完的待办"作为提示注入,让 Captain 接着干而不是从头来。
"""
from __future__ import annotations

import json
import os
import re
import time


class CheckpointStore:
    def __init__(self, base_dir: str = "logs/checkpoints") -> None:
        self.base = base_dir
        os.makedirs(base_dir, exist_ok=True)

    def _path(self, session: str) -> str:
        safe = re.sub(r"[^a-zA-Z0-9_.-]+", "_", session or "default")[:80]
        return os.path.join(self.base, f"{safe}.json")

    def save(self, session: str, steps: list[dict]) -> None:
        """steps: [{text, status}]。原子写。"""
        try:
            data = {"session": session, "ts": time.time(), "steps": steps}
            p = self._path(session)
            with open(p + ".tmp", "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(p + ".tmp", p)
        except Exception:
            pass

    def load(self, session: str) -> dict | None:
        p = self._path(session)
        if not os.path.isfile(p):
            return None
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def unfinished(self, session: str) -> list[str]:
        """返回还没 done 的待办文本列表(供续跑提示)。"""
        data = self.load(session)
        if not data:
            return []
        return [s.get("text", "") for s in data.get("steps", [])
                if s.get("status") not in ("done",) and s.get("text")]

    def clear(self, session: str) -> None:
        try:
            os.remove(self._path(session))
        except Exception:
            pass
