"""Durable office operation contracts: preview, authority, idempotency, audit."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class OfficeOperation:
    operation: str
    target: str
    payload: dict[str, Any] = field(default_factory=dict)
    authority: str = "read"
    idempotency_key: str = ""
    dry_run: bool = True

    def key(self) -> str:
        if self.idempotency_key:
            return self.idempotency_key
        raw = json.dumps({"operation": self.operation, "target": self.target,
                          "payload": self.payload}, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode()).hexdigest()


@dataclass
class OperationResult:
    ok: bool
    operation_id: str
    status: str
    output: Any = None
    error: str = ""
    preview: dict[str, Any] | None = None
    audit_id: str = ""


class OfficeKernel:
    """Small SQLite-backed operation ledger shared by all office adapters."""

    def __init__(self, db_path: str = "logs/office.db") -> None:
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("""CREATE TABLE IF NOT EXISTS office_operations (
            operation_id TEXT PRIMARY KEY, idempotency_key TEXT UNIQUE NOT NULL,
            operation TEXT NOT NULL, target TEXT NOT NULL, authority TEXT NOT NULL,
            payload TEXT NOT NULL, status TEXT NOT NULL, result TEXT,
            error TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL, updated_at REAL NOT NULL
        )""")
        self._conn.execute("""CREATE TABLE IF NOT EXISTS office_audit (
            audit_id TEXT PRIMARY KEY, operation_id TEXT NOT NULL, event TEXT NOT NULL,
            detail TEXT NOT NULL, created_at REAL NOT NULL
        )""")
        self._conn.commit()

    def preview(self, op: OfficeOperation) -> dict[str, Any]:
        return {"operation": op.operation, "target": op.target, "authority": op.authority,
                "idempotency_key": op.key(), "dry_run": op.dry_run,
                "payload": op.payload}

    def execute(self, op: OfficeOperation, handler: Callable[[], Any]) -> OperationResult:
        key = op.key()
        existing = self._conn.execute(
            "SELECT * FROM office_operations WHERE idempotency_key=?", (key,)).fetchone()
        if existing and existing["status"] == "completed":
            return OperationResult(True, existing["operation_id"], "deduplicated",
                                   json.loads(existing["result"] or "null"),
                                   audit_id=self._audit(existing["operation_id"], "deduplicated", "reused completed result"))
        operation_id = existing["operation_id"] if existing else uuid.uuid4().hex
        now = time.time()
        if not existing:
            self._conn.execute(
                "INSERT INTO office_operations VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (operation_id, key, op.operation, op.target, op.authority,
                 json.dumps(op.payload, ensure_ascii=False), "running", None, "", now, now))
            self._conn.commit()
        if op.dry_run:
            self._conn.execute("UPDATE office_operations SET status='previewed',updated_at=? WHERE operation_id=?", (now, operation_id))
            self._conn.commit()
            return OperationResult(True, operation_id, "previewed", preview=self.preview(op),
                                   audit_id=self._audit(operation_id, "preview", "write withheld by dry_run"))
        write_operation = op.operation.endswith((".create", ".update", ".delete", ".send", ".invite", ".write"))
        if write_operation and op.authority not in {"write", "send", "admin"}:
            message = "insufficient office authority for write operation"
            self._conn.execute("UPDATE office_operations SET status='blocked',error=?,updated_at=? WHERE operation_id=?",
                               (message, time.time(), operation_id))
            self._conn.commit()
            return OperationResult(False, operation_id, "blocked", error=message,
                                   audit_id=self._audit(operation_id, "blocked", message))
        try:
            output = handler()
            self._conn.execute("UPDATE office_operations SET status='completed',result=?,updated_at=? WHERE operation_id=?",
                               (json.dumps(output, ensure_ascii=False, default=str), time.time(), operation_id))
            self._conn.commit()
            return OperationResult(True, operation_id, "completed", output=output,
                                   audit_id=self._audit(operation_id, "completed", "handler returned successfully"))
        except Exception as exc:
            self._conn.execute("UPDATE office_operations SET status='failed',error=?,updated_at=? WHERE operation_id=?",
                               (str(exc), time.time(), operation_id))
            self._conn.commit()
            return OperationResult(False, operation_id, "failed", error=str(exc),
                                   audit_id=self._audit(operation_id, "failed", str(exc)))

    def _audit(self, operation_id: str, event: str, detail: str) -> str:
        audit_id = uuid.uuid4().hex
        self._conn.execute("INSERT INTO office_audit VALUES(?,?,?,?,?)",
                           (audit_id, operation_id, event, detail, time.time()))
        self._conn.commit()
        return audit_id

    def audit(self, operation_id: str | None = None) -> list[dict[str, Any]]:
        if operation_id:
            rows = self._conn.execute("SELECT * FROM office_audit WHERE operation_id=? ORDER BY created_at", (operation_id,)).fetchall()
        else:
            rows = self._conn.execute("SELECT * FROM office_audit ORDER BY created_at DESC").fetchall()
        return [dict(row) for row in rows]

    def close(self) -> None:
        self._conn.close()
