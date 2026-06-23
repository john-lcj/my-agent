"""项目空间持久化 —— 借鉴 Claude Projects:把"长期事"打包成一个项目。

一个项目 = 名称 + 专属指令(每条对话自动带上)+ 常驻知识文件(摘要注入上下文)。
会话通过 project_id 归属到项目(归属关系存在 sessions 表,见 session_store)。
存为 logs/projects.json,简单可手改;失败静默不拖累主流程。
"""
from __future__ import annotations

import json
import os
import time
import uuid


class ProjectStore:
    def __init__(self, path: str = "logs/projects.json") -> None:
        self.path = path
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._data: dict[str, dict] = self._read()

    def _read(self) -> dict:
        if not os.path.isfile(self.path):
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _write(self) -> None:
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def create(self, name: str, instructions: str = "", knowledge: list | None = None,
               workspace: str = "") -> dict:
        pid = "p_" + uuid.uuid4().hex[:10]
        now = time.time()
        proj = {
            "id": pid, "name": (name or "未命名项目").strip()[:60],
            "instructions": (instructions or "").strip(),
            "knowledge": [str(p) for p in (knowledge or [])],
            "workspace": (workspace or "").strip(),
            "created_at": now, "updated_at": now,
        }
        self._data[pid] = proj
        self._write()
        return proj

    def list(self) -> list[dict]:
        return sorted(self._data.values(), key=lambda p: p.get("updated_at", 0), reverse=True)

    def get(self, pid: str) -> dict | None:
        return self._data.get(pid)

    def update(self, pid: str, **fields) -> dict | None:
        proj = self._data.get(pid)
        if proj is None:
            return None
        for k in ("name", "instructions", "knowledge", "workspace"):
            if k in fields and fields[k] is not None:
                proj[k] = fields[k]
        proj["updated_at"] = time.time()
        self._write()
        return proj

    def delete(self, pid: str) -> bool:
        if pid in self._data:
            del self._data[pid]
            self._write()
            return True
        return False

    def context_block(self, pid: str, max_chars: int = 4000) -> str:
        """项目专属指令 + 知识文件摘要,拼成注入用的 system 块;无则空串。"""
        proj = self._data.get(pid)
        if not proj:
            return ""
        parts: list[str] = []
        instr = (proj.get("instructions") or "").strip()
        ws = (proj.get("workspace") or "").strip()
        if ws:
            parts.append(f"[工作区目录]\n{ws}")
        if instr:
            parts.append(f"[工作区「{proj.get('name','')}」专属指令]\n{instr}")
        budget = max_chars
        known: list[str] = []
        for path in proj.get("knowledge", []):
            p = os.path.expanduser(str(path))
            if not os.path.isfile(p) or budget <= 0:
                continue
            try:
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    txt = f.read(budget)
            except Exception:
                continue
            known.append(f"— {os.path.basename(p)} —\n{txt}")
            budget -= len(txt)
        if known:
            parts.append("[工作区知识库(供参考)]\n" + "\n\n".join(known))
        return "\n\n".join(parts)
