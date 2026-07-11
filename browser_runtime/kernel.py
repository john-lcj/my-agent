"""P5 browser kernel: identity, leases, redacted traces, and state assertions."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Callable


_SECRET_KEY = re.compile(r"(password|passwd|token|secret|cookie|authorization|api[_-]?key|code)", re.I)


@dataclass(frozen=True)
class BrowserContextKey:
    owner_id: str
    account_id: str
    project_id: str
    task_id: str

    def __post_init__(self) -> None:
        for value in asdict(self).values():
            if not str(value).strip() or any(char in str(value) for char in "\\/\n\r\t"):
                raise ValueError("browser context identifiers must be non-empty and path-safe")

    @property
    def value(self) -> str:
        raw = "|".join((self.owner_id, self.account_id, self.project_id, self.task_id))
        return hashlib.sha256(raw.encode()).hexdigest()


@dataclass(frozen=True)
class BrowserOperation:
    action: str
    target: str
    selector: str = ""
    data_classification: str = "public"
    high_impact: bool = False
    idempotency_key: str = ""

    def key(self, context: BrowserContextKey) -> str:
        if self.idempotency_key:
            return self.idempotency_key
        raw = json.dumps({"context": context.value, **asdict(self)}, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()


@dataclass
class BrowserLease:
    context_key: str
    lease_id: str
    owner_pid: int
    expires_at: float


@dataclass
class RemoteStateAssertion:
    description: str
    expected_url: str = ""
    required_text: tuple[str, ...] = ()
    forbidden_text: tuple[str, ...] = ()
    required_download_sha256: str = ""

    def verify(self, *, url: str = "", text: str = "", download_sha256: str = "") -> tuple[bool, str]:
        if self.expected_url and url != self.expected_url:
            return False, f"remote state URL mismatch: expected {self.expected_url}, got {url}"
        missing = [item for item in self.required_text if item not in text]
        if missing:
            return False, f"remote state missing required text: {', '.join(missing)}"
        present = [item for item in self.forbidden_text if item in text]
        if present:
            return False, f"remote state contains forbidden text: {', '.join(present)}"
        if self.required_download_sha256 and download_sha256 != self.required_download_sha256:
            return False, "download hash does not match the expected remote artifact"
        return True, "remote state verified"


@dataclass
class BrowserTrace:
    trace_id: str
    context_key: str
    operation_id: str
    action: str
    target: str
    url: str = ""
    accessibility: dict[str, Any] = field(default_factory=dict)
    screenshot_sha256: str = ""
    result: str = ""
    error: str = ""
    created_at: float = field(default_factory=time.time)
    previous_hash: str = ""

    def redacted(self) -> dict[str, Any]:
        return _redact(asdict(self))


def _redact(value: Any, key: str = "") -> Any:
    if _SECRET_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): _redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(item, key) for item in value]
    if isinstance(value, tuple):
        return [_redact(item, key) for item in value]
    if isinstance(value, str) and len(value) > 1200:
        return value[:1200] + "...[TRUNCATED]"
    return value


class BrowserKernel:
    """Durable browser operation/trace ledger; no browser engine dependency."""

    def __init__(self, db_path: str = "logs/browser_runtime.db", trace_path: str = "") -> None:
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("""CREATE TABLE IF NOT EXISTS browser_operations (
            operation_id TEXT PRIMARY KEY, context_key TEXT NOT NULL,
            idempotency_key TEXT UNIQUE NOT NULL, action TEXT NOT NULL,
            target TEXT NOT NULL, status TEXT NOT NULL, result TEXT,
            error TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL, updated_at REAL NOT NULL
        )""")
        self._conn.execute("""CREATE TABLE IF NOT EXISTS browser_leases (
            context_key TEXT PRIMARY KEY, lease_id TEXT NOT NULL,
            owner_pid INTEGER NOT NULL, expires_at REAL NOT NULL
        )""")
        self._conn.commit()
        self.trace_path = trace_path or os.path.join(os.path.dirname(db_path), "browser_traces.jsonl")

    def acquire(self, context: BrowserContextKey, ttl_seconds: float = 60.0) -> BrowserLease:
        now = time.time()
        current = self._conn.execute("SELECT * FROM browser_leases WHERE context_key=?", (context.value,)).fetchone()
        if current and current["expires_at"] > now:
            raise RuntimeError("browser context is already leased by another task")
        lease = BrowserLease(context.value, uuid.uuid4().hex, os.getpid(), now + ttl_seconds)
        self._conn.execute("INSERT OR REPLACE INTO browser_leases VALUES(?,?,?,?)",
                           (lease.context_key, lease.lease_id, lease.owner_pid, lease.expires_at))
        self._conn.commit()
        return lease

    def release(self, lease: BrowserLease) -> bool:
        cur = self._conn.execute("DELETE FROM browser_leases WHERE context_key=? AND lease_id=?",
                                 (lease.context_key, lease.lease_id))
        self._conn.commit()
        return bool(cur.rowcount)

    def execute(self, context: BrowserContextKey, operation: BrowserOperation,
                handler: Callable[[], Any]) -> dict[str, Any]:
        key = operation.key(context)
        row = self._conn.execute("SELECT * FROM browser_operations WHERE idempotency_key=?", (key,)).fetchone()
        if row and row["status"] == "completed":
            return {"ok": True, "status": "deduplicated", "operation_id": row["operation_id"],
                    "result": json.loads(row["result"] or "null")}
        operation_id = row["operation_id"] if row else uuid.uuid4().hex
        now = time.time()
        if not row:
            self._conn.execute("INSERT INTO browser_operations VALUES(?,?,?,?,?,?,?,?,?,?)",
                               (operation_id, context.value, key, operation.action, operation.target,
                                "running", None, "", now, now,))
            self._conn.commit()
        try:
            result = handler()
            self._conn.execute("UPDATE browser_operations SET status='completed',result=?,updated_at=? WHERE operation_id=?",
                               (json.dumps(result, ensure_ascii=False, default=str), time.time(), operation_id))
            self._conn.commit()
            return {"ok": True, "status": "completed", "operation_id": operation_id, "result": result}
        except Exception as exc:
            self._conn.execute("UPDATE browser_operations SET status='failed',error=?,updated_at=? WHERE operation_id=?",
                               (str(exc), time.time(), operation_id))
            self._conn.commit()
            return {"ok": False, "status": "failed", "operation_id": operation_id, "error": str(exc)}

    def append_trace(self, trace: BrowserTrace) -> str:
        parent = os.path.dirname(self.trace_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        previous = ""
        if os.path.isfile(self.trace_path):
            with open(self.trace_path, encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        previous = json.loads(line).get("hash", "")
        trace.previous_hash = previous
        payload = trace.redacted()
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        entry = {**payload, "hash": hashlib.sha256((previous + raw).encode()).hexdigest()}
        with open(self.trace_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry["hash"]

    def close(self) -> None:
        self._conn.close()
