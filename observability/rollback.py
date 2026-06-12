"""可回滚 —— 让"放手"真正安全。

思想:任何写/删类能力执行前,先做可撤销的备份(快照),出问题能一键还原。
- 文件已存在:把原文件备份到 snapshots/<trace_id>/,记录到清单。
- 文件不存在(本次新建):记录为 "created",回滚 = 删除该文件。

rollback(trace_id) 按清单逆序还原:恢复被覆盖的原文,删除新建的文件。
每个快照位置也会记录进清单,便于审计与回放。
"""
from __future__ import annotations

import json
import os
import shutil
import time


class RollbackManager:
    def __init__(self, snapshot_dir: str = "logs/snapshots") -> None:
        self.snapshot_dir = snapshot_dir

    def _trace_dir(self, trace_id: str) -> str:
        return os.path.join(self.snapshot_dir, trace_id)

    def _manifest_path(self, trace_id: str) -> str:
        return os.path.join(self._trace_dir(trace_id), "manifest.json")

    def _read_manifest(self, trace_id: str) -> list[dict]:
        path = self._manifest_path(trace_id)
        if not os.path.isfile(path):
            return []
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _write_manifest(self, trace_id: str, entries: list[dict]) -> None:
        os.makedirs(self._trace_dir(trace_id), exist_ok=True)
        with open(self._manifest_path(trace_id), "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)

    def snapshot(self, target_path: str, trace_id: str, call_id: str = "") -> None:
        """在一次写/删操作前为目标路径建立可还原的快照。"""
        target_path = os.path.expanduser(target_path)
        entries = self._read_manifest(trace_id)
        if os.path.isfile(target_path):
            backup_name = f"{call_id or len(entries)}__{os.path.basename(target_path)}"
            backup_path = os.path.join(self._trace_dir(trace_id), backup_name)
            os.makedirs(self._trace_dir(trace_id), exist_ok=True)
            shutil.copy2(target_path, backup_path)
            entries.append({"path": os.path.abspath(target_path), "backup": backup_path,
                            "kind": "overwrite", "ts": time.time()})
        else:
            entries.append({"path": os.path.abspath(target_path), "backup": None,
                            "kind": "created", "ts": time.time()})
        self._write_manifest(trace_id, entries)

    def rollback(self, trace_id: str) -> list[str]:
        """逆序还原该 trace 的所有改动,返回还原说明。"""
        entries = self._read_manifest(trace_id)
        notes: list[str] = []
        for entry in reversed(entries):
            path = entry["path"]
            if entry["kind"] == "overwrite" and entry.get("backup"):
                try:
                    shutil.copy2(entry["backup"], path)
                    notes.append(f"已还原(覆盖前内容):{path}")
                except Exception as e:
                    notes.append(f"还原失败 {path}:{e}")
            elif entry["kind"] == "created":
                try:
                    if os.path.isfile(path):
                        os.remove(path)
                    notes.append(f"已删除(本次新建):{path}")
                except Exception as e:
                    notes.append(f"删除失败 {path}:{e}")
        return notes or ["该任务没有可回滚的文件改动。"]
