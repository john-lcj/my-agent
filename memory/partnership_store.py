"""Durable Phase 7 state for proactive collaboration controls and evidence."""
from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any


class PartnershipStore:
    def __init__(self, path: str = "logs/partnership.json") -> None:
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    def _read(self) -> dict[str, Any]:
        default = {"settings": {"enabled": True, "interruption_budget": 3, "interruption_count": 0},
                   "commitments": [], "events": [], "profile": {"detail": "balanced", "intervention": "balanced"}}
        try:
            with open(self.path, encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                default.update(raw)
                return default
        except Exception:
            pass
        return default

    def _write(self, data: dict[str, Any]) -> None:
        temp = self.path + ".tmp"
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(temp, self.path)

    def settings(self) -> dict[str, Any]:
        return dict(self._read()["settings"])

    def update_settings(self, **changes: Any) -> dict[str, Any]:
        data = self._read(); settings = data["settings"]
        for key in ("enabled", "interruption_budget", "interruption_count"):
            if key in changes:
                settings[key] = bool(changes[key]) if key == "enabled" else max(0, int(changes[key]))
        self._write(data); return dict(settings)

    def profile(self) -> dict[str, Any]:
        return dict(self._read()["profile"])

    def update_profile(self, **changes: Any) -> dict[str, Any]:
        data = self._read()
        for key in ("detail", "intervention", "rhythm"):
            if key in changes and str(changes[key]).strip():
                data["profile"][key] = str(changes[key]).strip()[:80]
        self._write(data); return dict(data["profile"])

    def add_commitment(self, text: str, *, due: str = "", owner: str = "owner") -> dict[str, Any]:
        data = self._read(); now = time.time()
        row = {"id": uuid.uuid4().hex[:10], "text": text[:300], "due": due[:64], "owner": owner[:80],
               "status": "open", "created_at": now, "updated_at": now}
        data["commitments"].append(row); self._write(data); return row

    def commitments(self, status: str = "") -> list[dict[str, Any]]:
        rows = self._read()["commitments"]
        return [row for row in rows if not status or row.get("status") == status]

    def resolve_commitment(self, cid: str, status: str = "done") -> bool:
        data = self._read()
        for row in data["commitments"]:
            if row.get("id") == cid:
                row["status"] = status; row["updated_at"] = time.time(); self._write(data); return True
        return False

    def record(self, kind: str, detail: str, **metadata: Any) -> None:
        data = self._read()
        data["events"].append({"ts": time.time(), "kind": kind[:80], "detail": detail[:500], **metadata})
        data["events"] = data["events"][-500:]
        self._write(data)

    def events(self, days: float = 7.0) -> list[dict[str, Any]]:
        cutoff = time.time() - max(0, days) * 86400
        return [row for row in self._read()["events"] if row.get("ts", 0) >= cutoff]
