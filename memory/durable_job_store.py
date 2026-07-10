"""SQLite-WAL durable jobs, leases, steps, effects, checkpoints, and delivery.

This is the single source of truth for asynchronous work.  Callers may keep an
in-memory wake-up queue for latency, but correctness comes from this store.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from typing import Any


TERMINAL = {"completed", "failed", "cancelled", "dead_letter", "compensated"}
RETRYABLE = {"queued", "ready", "retrying", "waiting", "running", "verifying", "blocked"}
TRANSITIONS = {
    "queued": {"ready", "running", "cancelled"},
    "ready": {"running", "cancelled"},
    "running": {"blocked", "waiting", "verifying", "retrying", "completed", "failed", "cancelled", "dead_letter", "compensated"},
    "blocked": {"ready", "retrying", "cancelled"},
    "waiting": {"ready", "retrying", "cancelled"},
    "verifying": {"completed", "failed", "retrying", "cancelled"},
    "retrying": {"running", "dead_letter", "cancelled"},
    "failed": {"retrying", "dead_letter", "compensated"},
    "completed": set(), "cancelled": set(), "dead_letter": set(), "compensated": set(),
}


class DurableJobStore:
    def __init__(self, db_path: str = "logs/durable_jobs.db") -> None:
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA busy_timeout=30000")
        self._conn.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL, payload TEXT NOT NULL DEFAULT '{}',
            state TEXT NOT NULL DEFAULT 'queued', owner TEXT NOT NULL DEFAULT '',
            lease_until REAL NOT NULL DEFAULT 0, heartbeat_at REAL NOT NULL DEFAULT 0,
            attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 3,
            idempotency_key TEXT UNIQUE, deadline REAL NOT NULL DEFAULT 0,
            budget_seconds REAL NOT NULL DEFAULT 0, budget_cost REAL NOT NULL DEFAULT 0,
            spent_seconds REAL NOT NULL DEFAULT 0, spent_cost REAL NOT NULL DEFAULT 0,
            last_error TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL, updated_at REAL NOT NULL,
            completed_at REAL NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS job_steps (
            id TEXT PRIMARY KEY, job_id TEXT NOT NULL, position INTEGER NOT NULL,
            name TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'planned', payload TEXT NOT NULL DEFAULT '{}',
            result TEXT NOT NULL DEFAULT '{}', error TEXT NOT NULL DEFAULT '', updated_at REAL NOT NULL,
            UNIQUE(job_id, position), FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS job_checkpoints (
            id INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL, step_id TEXT NOT NULL DEFAULT '',
            snapshot TEXT NOT NULL, created_at REAL NOT NULL, FOREIGN KEY(job_id) REFERENCES jobs(id)
        );
        CREATE TABLE IF NOT EXISTS job_effects (
            effect_key TEXT PRIMARY KEY, job_id TEXT NOT NULL, kind TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'reserved', result TEXT NOT NULL DEFAULT '{}',
            created_at REAL NOT NULL, completed_at REAL NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS job_deliveries (
            id TEXT PRIMARY KEY, job_id TEXT NOT NULL, channel TEXT NOT NULL,
            destination TEXT NOT NULL, body TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL, updated_at REAL NOT NULL,
            UNIQUE(job_id, channel, destination)
        );
        CREATE INDEX IF NOT EXISTS idx_jobs_claim ON jobs(state, lease_until, created_at);
        CREATE INDEX IF NOT EXISTS idx_steps_job ON job_steps(job_id, position);
        """)
        for column, definition in (
            ("retry_at", "REAL NOT NULL DEFAULT 0"),
            ("cancel_requested", "INTEGER NOT NULL DEFAULT 0"),
            ("compensation", "TEXT NOT NULL DEFAULT ''"),
        ):
            try:
                self._conn.execute(f"ALTER TABLE jobs ADD COLUMN {column} {definition}")
            except sqlite3.OperationalError:
                pass
        self._conn.commit()

    def create_job(self, kind: str, payload: dict | None = None, *, idempotency_key: str = "",
                   max_attempts: int = 3, deadline: float = 0, budget_seconds: float = 0,
                   budget_cost: float = 0) -> dict:
        with self._lock:
            if idempotency_key:
                row = self._conn.execute("SELECT * FROM jobs WHERE idempotency_key=?", (idempotency_key,)).fetchone()
                if row:
                    return self._row(row)
            now = time.time()
            jid = uuid.uuid4().hex[:16]
            self._conn.execute(
                "INSERT INTO jobs(id,kind,payload,idempotency_key,max_attempts,deadline,budget_seconds,budget_cost,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (jid, kind, json.dumps(payload or {}, ensure_ascii=False), idempotency_key or None,
                 max(1, int(max_attempts)), float(deadline), float(budget_seconds), float(budget_cost), now, now),
            )
            self._conn.commit()
            return self.get(jid)

    def get(self, job_id: str) -> dict | None:
        row = self._conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return self._row(row) if row else None

    def list(self, states: set[str] | None = None, limit: int = 100) -> list[dict]:
        if states:
            marks = ",".join("?" for _ in states)
            rows = self._conn.execute(f"SELECT * FROM jobs WHERE state IN ({marks}) ORDER BY created_at LIMIT ?", (*states, limit)).fetchall()
        else:
            rows = self._conn.execute("SELECT * FROM jobs ORDER BY created_at LIMIT ?", (limit,)).fetchall()
        return [self._row(row) for row in rows]

    def claim(self, job_id: str, worker: str, lease_seconds: float = 30) -> dict | None:
        with self._lock:
            now = time.time()
            self._conn.execute("UPDATE jobs SET state='ready', owner='', lease_until=0 WHERE state='running' AND lease_until<?", (now,))
            cur = self._conn.execute(
                "UPDATE jobs SET state='running', owner=?, lease_until=?, heartbeat_at=?, attempts=attempts+1, updated_at=? WHERE id=? AND state IN ('queued','ready','retrying','waiting') AND (lease_until=0 OR lease_until<?)",
                (worker, now + lease_seconds, now, now, job_id, now),
            )
            self._conn.commit()
            return self.get(job_id) if cur.rowcount else None

    def claim_next(self, worker: str, lease_seconds: float = 30) -> dict | None:
        with self._lock:
            self.recover_stale()
            row = self._conn.execute("SELECT id FROM jobs WHERE state IN ('queued','ready','retrying') AND (retry_at=0 OR retry_at<=?) ORDER BY created_at LIMIT 1", (time.time(),)).fetchone()
            return self.claim(row[0], worker, lease_seconds) if row else None

    def heartbeat(self, job_id: str, worker: str, lease_seconds: float = 30) -> bool:
        now = time.time()
        cur = self._conn.execute("UPDATE jobs SET heartbeat_at=?, lease_until=?, updated_at=? WHERE id=? AND owner=? AND state='running'", (now, now + lease_seconds, now, job_id, worker))
        self._conn.commit()
        return bool(cur.rowcount)

    def recover_stale(self) -> int:
        now = time.time()
        cur = self._conn.execute("UPDATE jobs SET state=CASE WHEN attempts>=max_attempts THEN 'dead_letter' ELSE 'retrying' END, owner='', lease_until=0, last_error='stale lease recovered', updated_at=? WHERE state='running' AND lease_until<?", (now, now))
        self._conn.commit()
        return cur.rowcount

    def set_state(self, job_id: str, state: str, *, error: str = "", worker: str = "") -> dict:
        if state not in {"queued", "ready", "running", "blocked", "waiting", "verifying", "retrying", "completed", "failed", "cancelled", "dead_letter", "compensated"}:
            raise ValueError(f"invalid job state:{state}")
        current = self.get(job_id)
        if not current:
            raise KeyError(job_id)
        if current["state"] != state and state not in TRANSITIONS.get(current["state"], set()):
            raise ValueError(f"invalid job transition:{current['state']}->{state}")
        now = time.time()
        completed = now if state in TERMINAL else 0
        with self._lock:
            sql = "UPDATE jobs SET state=?,last_error=?,updated_at=?,completed_at=?,lease_until=CASE WHEN ? THEN 0 ELSE lease_until END,owner=CASE WHEN ? THEN '' ELSE owner END WHERE id=?"
            self._conn.execute(sql, (state, error[:2000], now, completed, state in TERMINAL, state in TERMINAL, job_id))
            self._conn.commit()
            return self.get(job_id)

    def add_steps(self, job_id: str, steps: list[dict | str]) -> list[dict]:
        now = time.time()
        with self._lock:
            for pos, raw in enumerate(steps):
                item = {"name": str(raw)} if isinstance(raw, str) else dict(raw)
                self._conn.execute("INSERT OR IGNORE INTO job_steps(id,job_id,position,name,payload,updated_at) VALUES(?,?,?,?,?,?)", (item.get("id") or uuid.uuid4().hex[:12], job_id, pos, str(item.get("name") or item.get("text") or f"step-{pos+1}"), json.dumps(item.get("payload") or {}, ensure_ascii=False), now))
            self._conn.commit()
        return self.steps(job_id)

    def steps(self, job_id: str) -> list[dict]:
        return [dict(row) for row in self._conn.execute("SELECT * FROM job_steps WHERE job_id=? ORDER BY position", (job_id,)).fetchall()]

    def set_step_state(self, step_id: str, state: str, *, result: dict | None = None, error: str = "") -> dict:
        allowed = {"planned", "ready", "running", "blocked", "waiting", "verifying", "retrying", "completed", "failed", "cancelled", "compensated"}
        if state not in allowed:
            raise ValueError(f"invalid step state:{state}")
        self._conn.execute("UPDATE job_steps SET state=?,result=?,error=?,updated_at=? WHERE id=?", (state, json.dumps(result or {}, ensure_ascii=False), error[:2000], time.time(), step_id))
        self._conn.commit()
        row = self._conn.execute("SELECT * FROM job_steps WHERE id=?", (step_id,)).fetchone()
        return dict(row) if row else {}

    def checkpoint(self, job_id: str, snapshot: dict, step_id: str = "") -> dict:
        self._conn.execute("INSERT INTO job_checkpoints(job_id,step_id,snapshot,created_at) VALUES(?,?,?,?)", (job_id, step_id, json.dumps(snapshot, ensure_ascii=False), time.time()))
        self._conn.commit()
        return {"job_id": job_id, "step_id": step_id, "snapshot": snapshot}

    def checkpoints(self, job_id: str, limit: int = 20) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM job_checkpoints WHERE job_id=? ORDER BY id DESC LIMIT ?", (job_id, limit)).fetchall()
        return [{**dict(row), "snapshot": json.loads(row["snapshot"])} for row in rows]

    def reserve_effect(self, job_id: str, effect_key: str, kind: str) -> bool:
        try:
            self._conn.execute("INSERT INTO job_effects(effect_key,job_id,kind,created_at) VALUES(?,?,?,?)", (effect_key, job_id, kind, time.time()))
            self._conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def complete_effect(self, effect_key: str, result: dict | None = None) -> bool:
        cur = self._conn.execute("UPDATE job_effects SET state='completed',result=?,completed_at=? WHERE effect_key=? AND state='reserved'", (json.dumps(result or {}, ensure_ascii=False), time.time(), effect_key))
        self._conn.commit()
        return bool(cur.rowcount)

    def release_effect(self, effect_key: str) -> bool:
        cur = self._conn.execute("DELETE FROM job_effects WHERE effect_key=? AND state='reserved'", (effect_key,))
        self._conn.commit()
        return bool(cur.rowcount)

    def queue_delivery(self, job_id: str, channel: str, destination: str, body: str) -> dict:
        now = time.time()
        self._conn.execute("INSERT OR IGNORE INTO job_deliveries(id,job_id,channel,destination,body,created_at,updated_at) VALUES(?,?,?,?,?,?,?)", (uuid.uuid4().hex[:16], job_id, channel, destination, body, now, now))
        self._conn.commit()
        row = self._conn.execute("SELECT * FROM job_deliveries WHERE job_id=? AND channel=? AND destination=?", (job_id, channel, destination)).fetchone()
        return dict(row)

    def set_delivery_state(self, delivery_id: str, state: str, *, error: str = "") -> dict:
        if state not in {"pending", "sending", "delivered", "failed", "cancelled"}:
            raise ValueError(f"invalid delivery state:{state}")
        self._conn.execute("UPDATE job_deliveries SET state=?,attempts=attempts+1,last_error=?,updated_at=? WHERE id=?", (state, error[:2000], time.time(), delivery_id))
        self._conn.commit()
        row = self._conn.execute("SELECT * FROM job_deliveries WHERE id=?", (delivery_id,)).fetchone()
        return dict(row) if row else {}

    def cancel(self, job_id: str, reason: str = "cancelled by owner") -> dict:
        return self.set_state(job_id, "cancelled", error=reason)

    def retry_or_dead_letter(self, job_id: str, error: str) -> dict:
        job = self.get(job_id)
        if not job:
            raise KeyError(job_id)
        state = "dead_letter" if job["attempts"] >= job["max_attempts"] else "retrying"
        result = self.set_state(job_id, state, error=error)
        if state == "retrying":
            delay = min(3600.0, 2 ** max(0, int(job["attempts"])))
            self._conn.execute("UPDATE jobs SET retry_at=?,updated_at=? WHERE id=?", (time.time() + delay, time.time(), job_id))
            self._conn.commit()
            result = self.get(job_id)
        return result

    def charge_budget(self, job_id: str, *, seconds: float = 0, cost: float = 0) -> dict:
        with self._lock:
            row = self.get(job_id)
            if not row:
                raise KeyError(job_id)
            spent_seconds = float(row["spent_seconds"]) + max(0, seconds)
            spent_cost = float(row["spent_cost"]) + max(0, cost)
            self._conn.execute("UPDATE jobs SET spent_seconds=?,spent_cost=?,updated_at=? WHERE id=?", (spent_seconds, spent_cost, time.time(), job_id))
            self._conn.commit()
            return self.get(job_id)

    def budget_exceeded(self, job_id: str) -> bool:
        row = self.get(job_id)
        if not row:
            return True
        return bool(
            (row["deadline"] and time.time() >= row["deadline"])
            or (row["budget_seconds"] and row["spent_seconds"] >= row["budget_seconds"])
            or (row["budget_cost"] and row["spent_cost"] >= row["budget_cost"])
        )

    def request_cancel(self, job_id: str, reason: str = "cancel requested") -> dict:
        self._conn.execute("UPDATE jobs SET cancel_requested=1,last_error=?,updated_at=? WHERE id=? AND state NOT IN ('completed','failed','cancelled','dead_letter','compensated')", (reason, time.time(), job_id))
        self._conn.commit()
        return self.get(job_id)

    def should_cancel(self, job_id: str) -> bool:
        row = self.get(job_id)
        return bool(row and row.get("cancel_requested"))

    def record_compensation(self, job_id: str, action: str) -> dict:
        self._conn.execute("UPDATE jobs SET compensation=?,state='compensated',completed_at=?,updated_at=? WHERE id=?", (action[:2000], time.time(), time.time(), job_id))
        self._conn.commit()
        return self.get(job_id)

    @staticmethod
    def _row(row: sqlite3.Row) -> dict:
        result = dict(row)
        result["payload"] = json.loads(result.get("payload") or "{}")
        return result

    def close(self) -> None:
        self._conn.close()
