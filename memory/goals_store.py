"""Durable goal graph used by proactive planning and briefings.

The public ``add/list/active_texts`` API remains compatible with the earlier
flat goal list.  New records are stored as graph nodes and explicit edges so
projects, milestones, owners, deadlines, and dependencies share one source of
truth.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any


_KINDS = {"goal", "project", "milestone", "interest", "reminder"}
_STATUSES = {"active", "paused", "completed", "cancelled"}
_RELATIONS = {"contains", "depends_on", "blocks", "supports"}


class GoalsStore:
    def __init__(self, path: str = "logs/goals.json") -> None:
        self.path = path
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)

    def _read_document(self) -> dict[str, list[dict[str, Any]]]:
        if not os.path.isfile(self.path):
            return {"nodes": [], "edges": []}
        try:
            with open(self.path, encoding="utf-8") as handle:
                raw = json.load(handle)
        except Exception:
            return {"nodes": [], "edges": []}
        # Migrate the former list format lazily and without losing its IDs.
        if isinstance(raw, list):
            return {"nodes": [self._normalize_legacy(row) for row in raw if isinstance(row, dict)], "edges": []}
        if not isinstance(raw, dict):
            return {"nodes": [], "edges": []}
        nodes = [self._normalize_legacy(row) for row in raw.get("nodes", []) if isinstance(row, dict)]
        edges = [dict(row) for row in raw.get("edges", []) if isinstance(row, dict)]
        return {"nodes": nodes, "edges": edges}

    @staticmethod
    def _normalize_legacy(row: dict[str, Any]) -> dict[str, Any]:
        kind = str(row.get("kind") or "goal").strip().lower()
        return {
            "id": str(row.get("id") or uuid.uuid4().hex[:10]),
            "text": str(row.get("text") or row.get("title") or "").strip(),
            "kind": kind if kind in _KINDS else "goal",
            "owner": str(row.get("owner") or "owner").strip() or "owner",
            "deadline": str(row.get("deadline") or "").strip(),
            "status": str(row.get("status") or ("active" if row.get("enabled", True) else "paused")).strip().lower(),
            "created_at": float(row.get("created_at") or time.time()),
            "updated_at": float(row.get("updated_at") or row.get("created_at") or time.time()),
            "enabled": bool(row.get("enabled", True)),
        }

    def _write_document(self, document: dict[str, list[dict[str, Any]]]) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump({"version": 2, **document}, handle, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def list(self) -> list[dict[str, Any]]:
        return self._read_document()["nodes"]

    def graph(self) -> dict[str, list[dict[str, Any]]]:
        return self._read_document()

    def add(self, text: str, kind: str = "goal", **metadata: Any) -> dict[str, Any]:
        return self.create_node(text, kind=kind, **metadata)

    def create_node(
        self,
        text: str,
        *,
        kind: str = "goal",
        owner: str = "owner",
        deadline: str = "",
        status: str = "active",
        enabled: bool = True,
    ) -> dict[str, Any]:
        text = (text or "").strip()
        if not text:
            raise ValueError("goal text is required")
        document = self._read_document()
        for row in document["nodes"]:
            if row.get("text") == text and row.get("kind") == kind:
                return row
        now = time.time()
        record = {
            "id": uuid.uuid4().hex[:10],
            "text": text[:300],
            "kind": kind if kind in _KINDS else "goal",
            "owner": (owner or "owner").strip()[:120] or "owner",
            "deadline": (deadline or "").strip()[:64],
            "status": status if status in _STATUSES else "active",
            "enabled": bool(enabled),
            "created_at": now,
            "updated_at": now,
        }
        document["nodes"].append(record)
        self._write_document(document)
        return record

    def update(self, node_id: str, **changes: Any) -> dict[str, Any] | None:
        document = self._read_document()
        allowed = {"text", "kind", "owner", "deadline", "status", "enabled"}
        for row in document["nodes"]:
            if row.get("id") != node_id:
                continue
            for key, value in changes.items():
                if key not in allowed or value is None:
                    continue
                if key == "kind" and str(value) not in _KINDS:
                    continue
                if key == "status" and str(value) not in _STATUSES:
                    continue
                row[key] = str(value).strip()[:300] if key not in {"enabled"} else bool(value)
            row["updated_at"] = time.time()
            self._write_document(document)
            return row
        return None

    def link(self, source_id: str, target_id: str, relation: str = "contains") -> dict[str, Any]:
        document = self._read_document()
        ids = {row.get("id") for row in document["nodes"]}
        if source_id not in ids or target_id not in ids:
            raise KeyError("goal graph node not found")
        if source_id == target_id:
            raise ValueError("goal graph cannot link a node to itself")
        relation = relation if relation in _RELATIONS else "contains"
        for edge in document["edges"]:
            if edge.get("source") == source_id and edge.get("target") == target_id and edge.get("relation") == relation:
                return edge
        edge = {"id": uuid.uuid4().hex[:10], "source": source_id, "target": target_id,
                "relation": relation, "created_at": time.time()}
        document["edges"].append(edge)
        self._write_document(document)
        return edge

    def remove(self, gid: str) -> bool:
        document = self._read_document()
        nodes = [row for row in document["nodes"] if row.get("id") != gid]
        if len(nodes) == len(document["nodes"]):
            return False
        document["nodes"] = nodes
        document["edges"] = [edge for edge in document["edges"] if gid not in {edge.get("source"), edge.get("target")}]
        self._write_document(document)
        return True

    def active_texts(self) -> list[str]:
        return [
            row["text"] for row in self._read_document()["nodes"]
            if row.get("enabled") and row.get("status") == "active" and row.get("text")
        ]
