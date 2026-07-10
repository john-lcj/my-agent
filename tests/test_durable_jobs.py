"""P2 durable runtime contract and fault-injection regressions."""
from __future__ import annotations

import multiprocessing
import sqlite3
import time

from memory.durable_job_store import DurableJobStore


def test_wal_queue_idempotency_leases_and_recovery(tmp_path):
    path = str(tmp_path / "jobs.db")
    store = DurableJobStore(path)
    first = store.create_job("mission", {"text": "do work"}, idempotency_key="effect-1")
    same = store.create_job("mission", {"text": "duplicate"}, idempotency_key="effect-1")
    assert first["id"] == same["id"]
    claimed = store.claim(first["id"], "worker-a", lease_seconds=0.01)
    assert claimed["state"] == "running"
    time.sleep(0.03)
    assert store.recover_stale() == 1
    recovered = store.get(first["id"])
    assert recovered["state"] == "retrying"
    assert store.claim(first["id"], "worker-b")["owner"] == "worker-b"


def test_process_restart_recovers_claimed_job(tmp_path):
    path = str(tmp_path / "restart.db")
    store = DurableJobStore(path)
    job = store.create_job("kill-test")
    store.claim(job["id"], "dead-worker", lease_seconds=0.01)
    store.close()
    time.sleep(0.03)
    restarted = DurableJobStore(path)
    assert restarted.recover_stale() == 1
    assert restarted.get(job["id"])["state"] == "retrying"


def test_steps_checkpoints_effects_delivery_and_cancel(tmp_path):
    store = DurableJobStore(str(tmp_path / "jobs.db"))
    job = store.create_job("workflow", {"goal": "x"}, max_attempts=2)
    steps = store.add_steps(job["id"], ["plan", {"name": "execute", "payload": {"x": 1}}])
    assert [s["name"] for s in steps] == ["plan", "execute"]
    store.set_step_state(steps[0]["id"], "completed", result={"evidence": "ok"})
    store.checkpoint(job["id"], {"completed_steps": [steps[0]["id"]], "assumptions": ["a"]}, steps[0]["id"])
    assert store.checkpoints(job["id"])[0]["snapshot"]["completed_steps"]
    assert store.reserve_effect(job["id"], "email:abc", "email")
    assert not store.reserve_effect(job["id"], "email:abc", "email")
    assert store.complete_effect("email:abc", {"receipt": "r"})
    delivery = store.queue_delivery(job["id"], "email", "owner@example.com", "done")
    assert delivery["state"] == "pending"
    assert store.cancel(job["id"])["state"] == "cancelled"


def test_retry_reaches_dead_letter(tmp_path):
    store = DurableJobStore(str(tmp_path / "jobs.db"))
    job = store.create_job("failing", max_attempts=1)
    store.claim(job["id"], "w")
    assert store.retry_or_dead_letter(job["id"], "permanent") ["state"] == "dead_letter"


def test_state_machine_rejects_invalid_transition(tmp_path):
    store = DurableJobStore(str(tmp_path / "jobs.db"))
    job = store.create_job("state")
    try:
        store.set_state(job["id"], "completed")
    except ValueError as exc:
        assert "transition" in str(exc)
    else:
        raise AssertionError("queued job must not jump directly to completed")


def test_sqlite_wal_enabled(tmp_path):
    path = str(tmp_path / "jobs.db")
    store = DurableJobStore(path)
    mode = store._conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"


def test_scheduler_execution_creates_durable_job(tmp_path):
    import asyncio
    from scheduler.scheduler import Scheduler
    from scheduler.store import TaskStore
    from core.task_outcome import TaskExecutionResult

    async def run_task(task, actor):
        return TaskExecutionResult.succeeded("done")

    task_store = TaskStore(str(tmp_path / "tasks.db"))
    durable = DurableJobStore(str(tmp_path / "jobs.db"))
    task = task_store.create(name="demo", prompt="do it", interval_sec=3600)
    scheduler = Scheduler(task_store, run_task, durable_jobs=durable)
    asyncio.run(scheduler.run_once(task))
    jobs = durable.list()
    assert len(jobs) == 1 and jobs[0]["kind"] == "scheduled"
    assert jobs[0]["state"] == "completed"
