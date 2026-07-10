"""Phase 0 foundation contracts: locking, identity, outcomes, and built-ins."""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from core.process_lock import ProcessFileLock
from core.runtime_identity import (
    build_bundle_stamp,
    runtime_source_hash,
    stamp_integrity_valid,
    validate_version_contract,
    write_bundle_stamp,
)
from core.task_outcome import RunOutcome, TaskExecutionResult, TaskStatus
from scheduler.scheduler import Scheduler, TaskAlreadyRunning
from scheduler.store import ScheduledTask
from scripts.stage_runtime import stage


ROOT = Path(__file__).resolve().parents[1]


def test_process_lock_is_exclusive_and_recoverable(tmp_path):
    path = tmp_path / "leader.lock"
    first = ProcessFileLock(str(path), role="first")
    second = ProcessFileLock(str(path), role="second")
    assert first.acquire({"port": "8000"}) is True
    assert second.acquire() is False
    assert second.owner()["port"] == "8000"
    first.release()
    assert second.acquire() is True
    second.release()


def test_version_contract_and_bundle_stamp(tmp_path):
    ok, values = validate_version_contract(str(ROOT))
    assert ok is True
    assert len(set(values.values())) == 1
    stamp = build_bundle_stamp(
        str(ROOT), target_platform="test", trust="development", commit="abc123"
    )
    out = tmp_path / ".captain_bundle_stamp"
    write_bundle_stamp(str(out), stamp)
    assert stamp_integrity_valid(stamp) is True
    assert stamp["frontend_hash"]
    assert stamp["source_hash"]
    assert stamp["schema_version"] == "1"


def test_runtime_staging_is_code_only(tmp_path):
    destination = tmp_path / "app"
    stage(ROOT, destination, preserve_state=False)
    assert (destination / "server/app.py").is_file()
    assert (destination / "frontend/app.js").is_file()
    assert not (destination / "desktop").exists()
    assert not list(destination.rglob("*.md"))
    stamp = build_bundle_stamp(
        str(ROOT), target_platform="test", trust="development", commit="abc123"
    )
    assert runtime_source_hash(str(destination)) == stamp["source_hash"]

    (destination / ".venv").mkdir()
    (destination / ".venv" / "README.md").write_text("dependency docs")
    stage(ROOT, destination, preserve_state=True)
    assert (destination / ".venv" / "README.md").is_file()


def test_model_text_cannot_override_failed_action():
    outcome = RunOutcome()
    outcome.action_failed("write failed")
    assert outcome.finalize() == TaskStatus.FAILED.value
    outcome.action_succeeded()
    assert outcome.finalize() == TaskStatus.PARTIAL.value


class _Store:
    def __init__(self):
        self.saved = None

    def save(self, task):
        self.saved = task

    def list(self):
        return []


def test_scheduler_separates_execution_and_delivery_failure():
    store = _Store()

    async def run_task(_task, _actor):
        return TaskExecutionResult(TaskStatus.PARTIAL.value, output="some work")

    async def deliver(*_args):
        raise RuntimeError("SMTP unavailable")

    scheduler = Scheduler(store, run_task, deliver)
    task = ScheduledTask(
        id="t1", name="test", prompt="run", deliver="email", deliver_to="me@example.com"
    )
    result = asyncio.run(scheduler.run_once(task))
    assert result.execution_status == TaskStatus.PARTIAL.value
    assert result.delivery_status == TaskStatus.FAILED.value
    assert result.last_status == TaskStatus.DELIVERY_FAILED.value
    assert "SMTP unavailable" in result.last_delivery_error


def test_scheduler_rejects_concurrent_duplicate_run():
    store = _Store()
    calls = 0

    async def scenario():
        nonlocal calls
        started = asyncio.Event()
        release = asyncio.Event()

        async def run_task(_task, _actor):
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            return TaskExecutionResult(TaskStatus.SUCCEEDED.value, output="done")

        scheduler = Scheduler(store, run_task)
        task = ScheduledTask(id="same", name="same", prompt="run")
        first = asyncio.create_task(scheduler.run_once(task))
        await started.wait()
        try:
            await scheduler.run_once(task)
        except TaskAlreadyRunning:
            pass
        else:
            raise AssertionError("concurrent duplicate run was accepted")
        release.set()
        await first

    asyncio.run(scenario())
    assert calls == 1


def test_every_builtin_scheduled_task_type(monkeypatch, tmp_path):
    import server.app as server_app
    from config import Config
    from server.async_tasks import _run_scheduled_task

    monkeypatch.setattr(Config, "LOG_DIR", str(tmp_path))
    monkeypatch.setattr(Config, "PERSONAL_DIRS", [])
    monkeypatch.setattr(server_app, "_longterm", SimpleNamespace(forget=lambda: 2))
    monkeypatch.setattr(server_app, "_mission_store", SimpleNamespace(list=lambda: []))
    actor = SimpleNamespace()

    def task(task_type, name="test", prompt="test"):
        return SimpleNamespace(task_type=task_type, name=name, prompt=prompt)

    forget = asyncio.run(_run_scheduled_task(task("memory_forget"), actor))
    rating = asyncio.run(_run_scheduled_task(task("rating_weekly"), actor))
    ingest = asyncio.run(_run_scheduled_task(task("memory_ingest"), actor))
    briefing = asyncio.run(_run_scheduled_task(task("briefing", "每日简报"), actor))
    assert forget.status == TaskStatus.SUCCEEDED.value
    assert rating.status == TaskStatus.SUCCEEDED.value
    assert ingest.status == TaskStatus.BLOCKED.value
    assert briefing.status == TaskStatus.SUCCEEDED.value

    ctx = SimpleNamespace(run_outcome=RunOutcome(), coworker=False, mem_scope="")

    class _Agent:
        async def run(self, *_args):
            ctx.run_outcome.action_succeeded()
            return "verified result"

    monkeypatch.setattr(server_app, "_build_scheduler_agent", lambda *_a, **_k: (_Agent(), ctx))
    generic = asyncio.run(_run_scheduled_task(task("agent"), actor))
    assert generic.status == TaskStatus.SUCCEEDED.value


def test_streaming_and_reconnect_regression_guards_are_packaged():
    source = (ROOT / "frontend/app.js").read_text(encoding="utf-8")
    assert "p.session_id === sessionId" in source
    assert "resetStreamingBubble()" in source
    assert "showToast(t('sendQueued')" in source
    assert "taskStatusBadge" in source
