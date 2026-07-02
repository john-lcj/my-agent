"""频道配置 + 定时任务 + 后台任务 API (从 app.py 抽出，行为不变)。"""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse


def register_channels(app, channel_cfg, ext_channels, enable_channel_fn, enable_channel_async_fn) -> None:
    """注册 /api/channels 和 /api/tasks 端点。"""

    @app.get("/api/channels")
    async def get_channels() -> JSONResponse:
        cfg = channel_cfg.get_masked()
        enabled = {"email": "email" in ext_channels}
        return JSONResponse({"config": cfg, "enabled": enabled})

    @app.post("/api/channels")
    async def save_channel(request: Request) -> JSONResponse:
        body = await request.json()
        channel = body.get("channel", "")
        values = body.get("values", {})
        channel_cfg.update(channel, values)
        return JSONResponse({"ok": True, "config": channel_cfg.get_masked()})

    @app.post("/api/channels/email/test")
    async def test_email(request: Request) -> JSONResponse:
        import asyncio
        from channels.email_channel import EmailChannel

        body = {}
        try:
            body = await request.json()
        except Exception:
            body = {}
        values = body.get("values") if isinstance(body, dict) else None
        if isinstance(values, dict) and values:
            channel_cfg.update("email", values)
        else:
            channel_cfg.apply_to_env()
        ch = EmailChannel()
        result = await asyncio.get_event_loop().run_in_executor(None, ch.test_connection)
        return JSONResponse(result)

    @app.post("/api/channels/{name}/restart")
    async def restart_channel(name: str) -> JSONResponse:
        channel_cfg.apply_to_env()
        ext_channels.pop(name, None)
        try:
            ok = await enable_channel_async_fn(name) if name == "email" else enable_channel_fn(name)
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)})
        return JSONResponse({"ok": ok})


def register_tasks(app, task_store, scheduler_holder, daemon_enqueue, daemon_results) -> None:
    """注册 /api/tasks 和 /api/task 端点。scheduler_holder 是 [Scheduler|None] 列表引用。"""

    @app.get("/api/tasks")
    async def get_tasks() -> JSONResponse:
        return JSONResponse({"tasks": [t.to_dict() for t in task_store.list()]})

    @app.post("/api/tasks")
    async def create_task(request: Request) -> JSONResponse:
        b = await request.json()
        task = task_store.create(
            name=b.get("name", "未命名任务"),
            prompt=b.get("prompt", ""),
            schedule_type=b.get("schedule_type", "every"),
            interval_sec=int(b.get("interval_sec", 3600)),
            at_hhmm=b.get("at_hhmm", "09:00"),
            deliver=b.get("deliver", "none"),
            deliver_to=b.get("deliver_to", ""),
            enabled=bool(b.get("enabled", True)),
            task_type=b.get("task_type", "agent"),
        )
        return JSONResponse({"ok": True, "task": task.to_dict()})

    @app.patch("/api/tasks/{task_id}")
    async def update_task(task_id: str, request: Request) -> JSONResponse:
        task = task_store.get(task_id)
        if task is None:
            return JSONResponse({"ok": False, "error": "任务不存在"}, status_code=404)
        b = await request.json()
        for field_name in ("name", "prompt", "schedule_type", "interval_sec",
                           "at_hhmm", "deliver", "deliver_to", "enabled", "task_type"):
            if field_name in b:
                setattr(task, field_name, b[field_name])
        task.next_run = task.compute_next_run()
        task_store.save(task)
        return JSONResponse({"ok": True, "task": task.to_dict()})

    @app.delete("/api/tasks/{task_id}")
    async def delete_task(task_id: str) -> JSONResponse:
        task_store.delete(task_id)
        return JSONResponse({"ok": True})

    @app.post("/api/tasks/{task_id}/run")
    async def run_task_now(task_id: str) -> JSONResponse:
        task = task_store.get(task_id)
        if task is None:
            return JSONResponse({"ok": False, "error": "任务不存在"}, status_code=404)
        scheduler = scheduler_holder[0]
        if scheduler is None:
            return JSONResponse({"ok": False, "error": "调度器未就绪"}, status_code=503)
        task = await scheduler.run_once(task)
        return JSONResponse({"ok": True, "task": task.to_dict()})

    @app.post("/api/task")
    async def submit_task(request: Request) -> JSONResponse:
        body = await request.json()
        text = str(body.get("text", "")).strip()
        if not text:
            return JSONResponse({"ok": False, "error": "缺少 text"}, status_code=400)
        mode = str(body.get("mode", "coworker")).strip() or "coworker"
        tid = daemon_enqueue(text, source="api", mode=mode)
        return JSONResponse({"ok": True, "task_id": tid})

    @app.get("/api/task/{tid}")
    async def get_daemon_task(tid: str) -> JSONResponse:
        rec = daemon_results.get(tid)
        if rec is None:
            return JSONResponse({"ok": False, "error": "任务不存在"}, status_code=404)
        return JSONResponse({"ok": True, "task": rec})
