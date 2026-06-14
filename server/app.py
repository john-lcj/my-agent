"""FastAPI 服务 —— /ws 流式聊天 + 外部渠道 webhook。

端点一览:
  GET  /           Web 前端(index.html)
  WS   /ws         WebSocket 聊天(流式 + 确认卡片)
  POST /webhook/wechat   企业微信消息接收
  GET  /webhook/wechat   企业微信 URL 验证
  POST /webhook/qq       QQ 机器人消息接收
  POST /api/email/send   手动触发邮件发送(调试用)

外部渠道按 .env 配置自动启用:
  EMAIL_USER      非空 => 启用邮件 Channel(后台轮询)
  WECHAT_CORP_ID  非空 => 启用企业微信 Channel
  QQ_BOT_APP_ID   非空 => 启用 QQ Channel

注意:不使用 `from __future__ import annotations`,且在模块顶层导入 FastAPI 的
WebSocket 等类型,否则 FastAPI 把参数误判为查询参数(握手 403)。
"""
import asyncio
import hmac
import ipaddress
import os
import time
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse

from config import Config, load_env
from core.bootstrap import build_agent_bundle
from core.coordinator_stack import build_coordinator_stack
from core.status_bar import emit_status_event
from core.types import Event, EventType, Identity
from channels.web import WebChannel
from channels.config_store import ChannelConfigStore
from core.persona import load_persona
from memory.factory import build_longterm
from memory.session_store import SessionStore
from scheduler.store import ScheduledTask, TaskStore
from scheduler.scheduler import Scheduler
from server.events import to_wire
from server.governance_stats import load_stats
from server.usage_stats import load_usage
from server.commands_api import list_slash_commands
from server.roster_api import list_roster_agents
from server.runtime_config import RuntimeConfigStore
from server.model_keys import ModelKeyStore, PROVIDER_KEY_ENV

_FRONTEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")

# ── 跨连接共享的单例:持久化会话、长期记忆、人设、频道配置、定时任务 ──────────
_session_store = SessionStore(db_path=f"{Config.LOG_DIR}/sessions.db")
_session_locks: dict[str, asyncio.Lock] = {}


def _session_lock(session_id: str) -> asyncio.Lock:
    lock = _session_locks.get(session_id)
    if lock is None:
        lock = asyncio.Lock()
        _session_locks[session_id] = lock
    return lock
_longterm = build_longterm(Config.LOG_DIR)
_persona = load_persona()
_runtime_cfg = RuntimeConfigStore(path=f"{Config.LOG_DIR}/runtime.json")
_ROSTER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agents", "roster")
# 频道配置:实例化即把 logs/channels.json 写入 os.environ(必须在 startup 读 env 前完成)。
_channel_cfg = ChannelConfigStore(path=f"{Config.LOG_DIR}/channels.json")
# 模型 API key:同样实例化即把 logs/model_keys.json 写入 os.environ,
# 这样网页里填的 key 在后续构建 LLM / 查询 /api/models 时即刻生效。
_model_keys = ModelKeyStore(path=f"{Config.LOG_DIR}/model_keys.json")
_task_store = TaskStore(db_path=f"{Config.LOG_DIR}/tasks.db")
_scheduler: "Scheduler | None" = None

# ── 外部渠道注册表(启动时按 .env 填充)───────────────────────────────────────
_ext_channels: dict[str, object] = {}
_ext_coordinators: dict[str, object] = {}
_ext_templates: dict[str, object] = {}


def _qq_env_ready() -> bool:
    app_id = os.environ.get("QQ_BOT_APP_ID", "")
    secret = os.environ.get("QQ_BOT_SECRET", "") or os.environ.get("QQ_BOT_TOKEN", "")
    return bool(app_id and secret)


def _pref_mining_enabled() -> bool:
    """偏好沉淀开关:配置开启且当前模型不是 mock(mock 抽不出有意义的偏好)。"""
    if not Config.PREF_MINING:
        return False
    return (_runtime_cfg.get_model() or "").lower() != "mock"


async def _mine_preferences(messages: list) -> None:
    """会话任务结束后异步抽取偏好,失败静默(绝不影响主对话)。"""
    try:
        from llm.factory import build_llm
        from memory.preference_miner import PreferenceMiner

        miner = PreferenceMiner(build_llm(model=_runtime_cfg.get_model()), _longterm)
        stored = await miner.mine(messages)
        if stored:
            print(f"[pref] 沉淀偏好 {len(stored)} 条: {stored}")
    except Exception:
        pass


async def _consolidate_journal(messages: list) -> None:
    """会话任务结束后异步写一条协作日志,失败静默(绝不影响主对话)。"""
    try:
        from llm.factory import build_llm
        from memory.journal import Journal, JournalConsolidator

        consolidator = JournalConsolidator(
            build_llm(model=_runtime_cfg.get_model()), Journal())
        if await consolidator.consolidate(messages):
            print("[journal] 已沉淀一条协作日志")
    except Exception:
        pass


def build_core(channel: WebChannel, model: Optional[str] = None):
    """为一个 web 会话装配 Coordinator + bundle。"""
    model_id = model or _runtime_cfg.get_model()
    coordinator, bundle = build_coordinator_stack(
        channel.identity(),
        profile="interactive",
        longterm=_longterm,
        persona=_persona,
        event_sink=channel.emit,
        model=model_id,
        max_cost_usd=_runtime_cfg.get_max_cost_usd(),
        governance_mode=_runtime_cfg.get_governance_mode(),
    )
    return coordinator, bundle


def _build_ext_stack(channel):
    """为外部 Channel(邮件/微信/QQ)装配 Coordinator + 系统头模板。"""
    return build_coordinator_stack(
        channel.identity(),
        profile="external",
        longterm=_longterm,
        persona=_persona,
        event_sink=channel.emit,
    )


def _build_scheduler_agent(actor: Identity):
    """为定时任务装配 headless agent。"""
    bundle = build_agent_bundle(
        actor,
        profile="interactive",
        longterm=_longterm,
        persona=_persona,
        with_rollback=False,
    )
    return bundle.agent, bundle.ctx


async def _run_scheduled_task(task: ScheduledTask, actor: Identity) -> str:
    """定时任务执行入口:confirm 恒为 False(无人值守 → 自动拒绝需确认的动作)。"""
    if task.task_type == "memory_forget":
        removed = _longterm.forget()
        return f"记忆清理完成,删除 {removed} 条低价值记忆"

    if task.task_type == "memory_ingest":
        if not Config.PERSONAL_DIRS:
            return "未配置 AGENT_PERSONAL_DIRS,跳过个人数据索引"
        from memory.ingest import ingest_dirs
        stats = ingest_dirs(
            Config.PERSONAL_DIRS, _longterm,
            state_path=f"{Config.LOG_DIR}/ingest_state.json",
        )
        return (f"个人数据索引完成:扫描 {stats['scanned']},新索引 {stats['indexed']},"
                f"未变跳过 {stats['skipped']},清理旧块 {stats['removed_chunks']}")

    agent, ctx = _build_scheduler_agent(actor)

    async def deny(call, decision, reason=""):
        return False

    return await agent.run(task.prompt, ctx, deny)


async def _deliver_result(channel: str, to: str, subject: str, body: str) -> None:
    """把定时任务结果投递到外部渠道(best-effort)。"""
    ch = _ext_channels.get(channel)
    if ch is None:
        print(f"[scheduler] 渠道 {channel} 未启用,跳过投递")
        return
    if channel == "email":
        target = to or ch.user
        await ch._send_email(target, subject, body)
    elif channel == "wechat":
        target = to or "@all"
        await ch._send_text(target, f"{subject}\n\n{body}")
    elif channel == "qq":
        if not to:
            raise ValueError("QQ 投递需 deliver_to,格式 group:<id> / user:<id> / channel:<id>")
        await ch.send_proactive(to, subject, body)
    elif channel == "slack":
        await ch.send_proactive(to, f"{subject}\n\n{body}")
    elif channel == "telegram":
        await ch.send_proactive(to, f"{subject}\n\n{body}")


def _enable_channel(name: str) -> bool:
    """同步启用渠道(不含 email 轮询启动,轮询由 _enable_channel_async 处理)。"""
    if name == "email" and os.environ.get("EMAIL_USER"):
        from channels.email_channel import EmailChannel
        ch = EmailChannel()
        coordinator, bundle = _build_ext_stack(ch)
        _ext_channels["email"] = ch
        _ext_coordinators["email"] = coordinator
        _ext_templates["email"] = bundle.ctx
        return True
    if name == "wechat" and os.environ.get("WECHAT_CORP_ID"):
        from channels.wechat_channel import WeChatChannel
        ch = WeChatChannel()
        coordinator, bundle = _build_ext_stack(ch)
        _ext_channels["wechat"] = ch
        _ext_coordinators["wechat"] = coordinator
        _ext_templates["wechat"] = bundle.ctx
        asyncio.create_task(_run_ext_channel("wechat"))
        return True
    if name == "qq" and _qq_env_ready():
        from channels.qq_channel import QQChannel, qq_channel_info
        ch = QQChannel()
        coordinator, bundle = _build_ext_stack(ch)
        _ext_channels["qq"] = ch
        _ext_coordinators["qq"] = coordinator
        _ext_templates["qq"] = bundle.ctx
        asyncio.create_task(_run_ext_channel("qq"))
        info = qq_channel_info()
        print(f"[server] QQ webhook → {info['webhook_url']} (沙箱={info['sandbox']})")
        return True
    if name == "slack" and os.environ.get("SLACK_BOT_TOKEN"):
        from channels.slack_channel import SlackChannel
        ch = SlackChannel()
        coordinator, bundle = _build_ext_stack(ch)
        _ext_channels["slack"] = ch
        _ext_coordinators["slack"] = coordinator
        _ext_templates["slack"] = bundle.ctx
        asyncio.create_task(_run_ext_channel("slack"))
        return True
    if name == "telegram" and os.environ.get("TELEGRAM_BOT_TOKEN"):
        from channels.telegram_channel import TelegramChannel
        ch = TelegramChannel()
        coordinator, bundle = _build_ext_stack(ch)
        _ext_channels["telegram"] = ch
        _ext_coordinators["telegram"] = coordinator
        _ext_templates["telegram"] = bundle.ctx
        asyncio.create_task(_run_ext_channel("telegram"))
        return True
    return False


async def _enable_channel_async(name: str) -> bool:
    """异步启用渠道(含邮件 IMAP 轮询)。"""
    if name == "email" and os.environ.get("EMAIL_USER"):
        from channels.email_channel import EmailChannel
        ch = EmailChannel()
        coordinator, bundle = _build_ext_stack(ch)
        _ext_channels["email"] = ch
        _ext_coordinators["email"] = coordinator
        _ext_templates["email"] = bundle.ctx
        await ch.start_polling()
        asyncio.create_task(_run_ext_channel("email"))
        return True
    return _enable_channel(name)


async def _run_ext_channel(channel_name: str) -> None:
    """外部渠道的消息处理循环:receive → coordinator.run → emit(自动回复)。"""
    from core.context import Context
    from core.types import Message, Role

    channel = _ext_channels[channel_name]
    coordinator = _ext_coordinators[channel_name]
    template = _ext_templates[channel_name]
    system_hdr = (
        template.messages[0].content if template.messages else ""
    )

    while True:
        try:
            text = await channel.receive()
            if text is None:
                break
            identity = channel.identity()
            session_id = f"{channel_name}:{identity.subject_id}"
            async with _session_lock(session_id):
                msg_ctx = Context(identity=identity)
                msg_ctx.bind_session(_session_store, session_id)
                if system_hdr and (
                    not msg_ctx.messages
                    or msg_ctx.messages[0].role != Role.SYSTEM
                ):
                    msg_ctx.messages.insert(
                        0, Message(role=Role.SYSTEM, content=system_hdr),
                    )
                await coordinator.run(text, msg_ctx, channel.confirm)
        except Exception as e:
            print(f"[{channel_name}] 处理异常: {e}")


async def _register_mcp_tools(config_path: str = "mcp_servers.json") -> None:
    """连接 mcp_servers.json 里的 MCP server,把工具注册为全局附加能力。fail-soft。"""
    try:
        from capabilities.mcp_connector import (
            load_mcp_servers, connect_stdio_server, MCPConnector,
        )
        from core.bootstrap import register_extra_capability
    except Exception:
        return
    specs = load_mcp_servers(config_path)
    if not specs:
        return
    for spec in specs:
        if not spec.get("command"):
            continue  # 暂只支持 stdio 型(HTTP 型留待后续)
        try:
            client = await connect_stdio_server(
                spec["command"], spec.get("args"), spec.get("env"))
            caps = await MCPConnector(spec["name"], client).discover()
            for cap in caps:
                register_extra_capability(cap)
            print(f"[mcp] {spec['name']}: 注册 {len(caps)} 个工具")
        except Exception as e:
            print(f"[mcp] {spec['name']} 连接失败(已跳过): {e}")


def create_app():
    load_env()
    # ── 生命周期:启动时初始化外部渠道 + 定时任务调度器,关闭时停掉调度器 ──
    @asynccontextmanager
    async def _lifespan(_app: FastAPI):
        for name in ("email", "wechat", "qq", "slack", "telegram"):
            try:
                ok = await _enable_channel_async(name) if name == "email" else _enable_channel(name)
                if ok:
                    print(f"[server] {name} 渠道已启动")
            except Exception as e:
                print(f"[server] {name} 渠道启动失败: {e}")

        global _scheduler
        _scheduler = Scheduler(_task_store, _run_scheduled_task, _deliver_result)
        _scheduler.start()
        print(f"[server] 定时任务调度器已启动({len(_task_store.list())} 个任务)")

        from core.briefing import ensure_briefing_task
        if ensure_briefing_task(
            _task_store,
            at_hhmm=Config.BRIEFING_AT,
            channel=Config.BRIEFING_CHANNEL,
            to=Config.BRIEFING_TO,
        ):
            print(f"[server] 已注册每日简报任务({Config.BRIEFING_AT} → {Config.BRIEFING_CHANNEL})")

        if Config.PERSONAL_DIRS and not any(
            t.task_type == "memory_ingest" for t in _task_store.list()
        ):
            _task_store.create(
                name="个人数据索引",
                prompt="(内置任务)扫描 AGENT_PERSONAL_DIRS 目录,增量索引个人文档到长期记忆",
                schedule_type="daily",
                at_hhmm="03:30",
                deliver="none",
                task_type="memory_ingest",
            )
            print(f"[server] 已注册个人数据索引任务({len(Config.PERSONAL_DIRS)} 个目录,每天 03:30)")

        # 外部连接器:按 mcp_servers.json 连接 MCP server,把其工具注册为全局附加能力,
        # 之后每个会话的 registry 都会带上(同样过治理)。fail-soft:无配置/无 SDK 即跳过。
        await _register_mcp_tools()

        yield
        if _scheduler is not None:
            _scheduler.stop()

    app = FastAPI(title="my-agent", lifespan=_lifespan)

    # ── 控制面鉴权(security-by-default)─────────────────────────────────────────
    # /api/* 是完整控制面(改配置、删会话、回滚、录入模型 key……)。
    # 策略:本机(loopback)请求照常放行,保持本地零配置体验;非本机访问 /api/*
    # 必须带 X-Agent-Token==AGENT_API_TOKEN,否则 401。这样默认仅绑 127.0.0.1 时
    # 完全无感,一旦 --host 0.0.0.0 对外暴露,控制面就不再是无认证敞口。
    def _is_loopback(host: str) -> bool:
        if host in ("localhost", ""):
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    @app.middleware("http")
    async def _api_auth(request: Request, call_next):
        if request.url.path.startswith("/api/"):
            client = request.client.host if request.client else ""
            if not _is_loopback(client):
                token = os.environ.get("AGENT_API_TOKEN", "").strip()
                provided = request.headers.get("x-agent-token", "")
                if not token or not hmac.compare_digest(provided, token):
                    return JSONResponse(
                        {"error": "unauthorized",
                         "detail": "远程访问 /api/* 需设置 AGENT_API_TOKEN 并在 X-Agent-Token 头携带。"},
                        status_code=401,
                    )
        return await call_next(request)

    # ── 企业微信 webhook ─────────────────────────────────────────────────────
    @app.get("/webhook/wechat")
    async def wechat_verify(request: Request) -> HTMLResponse:
        ch = _ext_channels.get("wechat")
        if ch is None:
            return HTMLResponse("wechat channel not enabled", status_code=404)
        params = dict(request.query_params)
        echostr = await ch.handle_verification(params)
        return HTMLResponse(echostr)

    @app.post("/webhook/wechat")
    async def wechat_message(request: Request) -> HTMLResponse:
        ch = _ext_channels.get("wechat")
        if ch is None:
            return HTMLResponse("wechat channel not enabled", status_code=404)
        body = await request.body()
        params = dict(request.query_params)
        result = await ch.handle_message(body, params)
        return HTMLResponse(result)

    # ── QQ 机器人 webhook ─────────────────────────────────────────────────────
    @app.post("/webhook/qq")
    async def qq_callback(request: Request) -> JSONResponse:
        ch = _ext_channels.get("qq")
        if ch is None:
            return JSONResponse({"error": "qq channel not enabled"}, status_code=404)
        body = await request.body()
        headers = dict(request.headers)
        result = await ch.handle_callback(body, headers)
        return JSONResponse(result)

    @app.post("/webhook/slack")
    async def slack_events(request: Request) -> JSONResponse:
        ch = _ext_channels.get("slack")
        if ch is None:
            return JSONResponse({"error": "slack channel not enabled"}, status_code=404)
        body = await request.body()
        result = await ch.handle_webhook(body, dict(request.headers))
        return JSONResponse(result)

    @app.post("/webhook/telegram")
    async def telegram_webhook(request: Request) -> JSONResponse:
        ch = _ext_channels.get("telegram")
        if ch is None:
            return JSONResponse({"error": "telegram channel not enabled"}, status_code=404)
        body = await request.body()
        result = await ch.handle_webhook(body, dict(request.headers))
        return JSONResponse(result)

    # ── 频道配置 API ─────────────────────────────────────────────────────────
    @app.get("/api/channels")
    async def get_channels() -> JSONResponse:
        cfg = _channel_cfg.get_masked()
        enabled = {n: (n in _ext_channels) for n in ("email", "wechat", "qq", "slack", "telegram")}
        return JSONResponse({"config": cfg, "enabled": enabled})

    @app.post("/api/channels")
    async def save_channel(request: Request) -> JSONResponse:
        body = await request.json()
        channel = body.get("channel", "")
        values = body.get("values", {})
        _channel_cfg.update(channel, values)
        return JSONResponse({"ok": True, "config": _channel_cfg.get_masked()})

    @app.post("/api/channels/email/test")
    async def test_email(request: Request) -> JSONResponse:
        from channels.email_channel import EmailChannel
        ch = EmailChannel()  # 从已应用的 env 读取配置
        result = await asyncio.get_event_loop().run_in_executor(None, ch.test_connection)
        return JSONResponse(result)

    @app.get("/api/channels/qq/info")
    async def qq_info(request: Request) -> JSONResponse:
        from channels.qq_channel import qq_channel_info
        base = str(request.base_url).rstrip("/")
        info = qq_channel_info(public_base_url=base)
        info["enabled"] = "qq" in _ext_channels
        return JSONResponse(info)

    @app.post("/api/channels/qq/test")
    async def test_qq(request: Request) -> JSONResponse:
        from channels.qq_channel import QQChannel
        ch = QQChannel()
        return JSONResponse(await ch.test_connection())

    @app.post("/api/channels/{name}/restart")
    async def restart_channel(name: str) -> JSONResponse:
        _channel_cfg.apply_to_env()
        _ext_channels.pop(name, None)
        try:
            ok = await _enable_channel_async(name) if name == "email" else _enable_channel(name)
        except Exception as e:
            return JSONResponse({"ok": False, "error": str(e)})
        return JSONResponse({"ok": ok})

    # ── 定时任务 API ─────────────────────────────────────────────────────────
    @app.get("/api/tasks")
    async def get_tasks() -> JSONResponse:
        return JSONResponse({"tasks": [t.to_dict() for t in _task_store.list()]})

    @app.post("/api/tasks")
    async def create_task(request: Request) -> JSONResponse:
        b = await request.json()
        task = _task_store.create(
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
        task = _task_store.get(task_id)
        if task is None:
            return JSONResponse({"ok": False, "error": "任务不存在"}, status_code=404)
        b = await request.json()
        for field_name in ("name", "prompt", "schedule_type", "interval_sec",
                           "at_hhmm", "deliver", "deliver_to", "enabled", "task_type"):
            if field_name in b:
                setattr(task, field_name, b[field_name])
        task.next_run = task.compute_next_run()
        _task_store.save(task)
        return JSONResponse({"ok": True, "task": task.to_dict()})

    @app.delete("/api/tasks/{task_id}")
    async def delete_task(task_id: str) -> JSONResponse:
        _task_store.delete(task_id)
        return JSONResponse({"ok": True})

    @app.post("/api/tasks/{task_id}/run")
    async def run_task_now(task_id: str) -> JSONResponse:
        task = _task_store.get(task_id)
        if task is None:
            return JSONResponse({"ok": False, "error": "任务不存在"}, status_code=404)
        if _scheduler is None:
            return JSONResponse({"ok": False, "error": "调度器未就绪"}, status_code=503)
        task = await _scheduler.run_once(task)
        return JSONResponse({"ok": True, "task": task.to_dict()})

    @app.get("/")
    async def index() -> HTMLResponse:
        index_path = os.path.join(_FRONTEND, "index.html")
        if not os.path.isfile(index_path):
            return HTMLResponse(
                "<h1>前端文件缺失</h1>"
                f"<p>找不到 <code>{index_path}</code>。</p>"
                "<p>请在完整项目目录启动服务,例如:</p>"
                "<pre>cd \"~/Desktop/my agent\"\n"
                "python3 -m uvicorn server.app:app --host 127.0.0.1 --port 8000</pre>",
                status_code=503,
            )
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())

    @app.get("/api/sessions")
    async def list_sessions() -> JSONResponse:
        return JSONResponse({"sessions": _session_store.list_sessions()})

    async def _rename_session(session_id: str, title: str) -> JSONResponse:
        if not _session_store.update_title(session_id, title):
            return JSONResponse({"ok": False, "error": "会话不存在"}, status_code=404)
        return JSONResponse({"ok": True, "title": title})

    @app.patch("/api/sessions/{session_id}")
    async def rename_session(session_id: str, request: Request) -> JSONResponse:
        body = await request.json()
        title = str(body.get("title", "")).strip()
        return await _rename_session(session_id, title)

    @app.post("/api/sessions/{session_id}/rename")
    async def rename_session_post(session_id: str, request: Request) -> JSONResponse:
        body = await request.json()
        title = str(body.get("title", "")).strip()
        return await _rename_session(session_id, title)

    @app.delete("/api/sessions/{session_id}")
    async def delete_session(session_id: str) -> JSONResponse:
        _session_store.delete_session(session_id)
        return JSONResponse({"ok": True})

    @app.get("/api/sessions/{session_id}/roundtable")
    async def get_roundtable_session(session_id: str) -> JSONResponse:
        data = _session_store.load_roundtable(session_id)
        if not data:
            return JSONResponse({"error": "圆桌记录不存在"}, status_code=404)
        return JSONResponse(data)

    @app.post("/api/rollback")
    async def rollback_last(request: Request) -> JSONResponse:
        body = await request.json()
        trace_id = body.get("trace_id", "")
        notes: list[str] = []
        # Web 连接各自持有 bundle;此处用模块级最近一次 trace 需由客户端传入。
        from observability.rollback import RollbackManager
        rb = RollbackManager(snapshot_dir=f"{Config.LOG_DIR}/snapshots")
        if not trace_id:
            return JSONResponse({"ok": False, "error": "缺少 trace_id"}, status_code=400)
        notes = rb.rollback(trace_id)
        return JSONResponse({"ok": True, "notes": notes})

    @app.get("/api/models")
    async def list_models_api(all: bool = False, current: str = "") -> JSONResponse:
        from llm.model_registry import MODELS, is_model_configured, normalize_model_id

        cur = normalize_model_id(current) if current else None
        out = []
        seen: set[str] = set()
        for m in MODELS:
            configured = is_model_configured(m.id)
            if all or configured or (cur and m.id == cur):
                out.append({
                    "id": m.id,
                    "label": m.label,
                    "provider": m.provider,
                    "context": m.context,
                    "configured": configured,
                })
                seen.add(m.id)
        if cur and cur not in seen:
            spec = next((m for m in MODELS if m.id == cur), None)
            if spec:
                out.insert(0, {
                    "id": spec.id,
                    "label": spec.label,
                    "provider": spec.provider,
                    "context": spec.context,
                    "configured": is_model_configured(spec.id),
                })
        return JSONResponse({"models": out})

    @app.get("/api/config")
    async def get_runtime_config() -> JSONResponse:
        cfg = _runtime_cfg.load()
        model_id = _runtime_cfg.get_model()
        return JSONResponse({
            "model": model_id,
            "provider": cfg.get("provider", _runtime_cfg.get_provider()),
            "max_cost_usd": cfg.get("max_cost_usd", Config.MAX_COST_USD),
            "governance_mode": cfg.get("governance_mode", Config.GOVERNANCE_MODE),
        })

    @app.post("/api/config")
    async def save_runtime_config(request: Request) -> JSONResponse:
        from llm.model_registry import get_model, normalize_model_id

        body = await request.json()
        allowed = {
            k: body[k] for k in ("max_cost_usd", "governance_mode") if k in body
        }
        if "model" in body:
            mid = normalize_model_id(str(body["model"]))
            if mid:
                allowed["model"] = mid
                allowed["provider"] = get_model(mid).provider
        elif "provider" in body:
            mid = normalize_model_id(str(body["provider"]))
            if mid:
                allowed["model"] = mid
                allowed["provider"] = get_model(mid).provider
        saved = _runtime_cfg.save(allowed)
        return JSONResponse({"ok": True, "config": saved})

    # ── 模型 API key 管理(网页里填 key 即可连模型)──────────────────────────────
    @app.get("/api/keys")
    async def get_model_keys() -> JSONResponse:
        return JSONResponse({"keys": _model_keys.get_masked()})

    @app.post("/api/keys")
    async def save_model_keys(request: Request) -> JSONResponse:
        body = await request.json()
        # 兼容两种入参:{"values": {...}} 或直接 {"provider": "...", "key": "..."}
        values = body.get("values")
        if values is None and "provider" in body:
            values = {body.get("provider", ""): body.get("key", "")}
        _model_keys.update(values or {})
        return JSONResponse({"ok": True, "keys": _model_keys.get_masked()})

    @app.delete("/api/keys/{provider}")
    async def delete_model_key(provider: str) -> JSONResponse:
        if provider not in PROVIDER_KEY_ENV:
            return JSONResponse({"ok": False, "error": "未知 provider"}, status_code=404)
        ok = _model_keys.clear(provider)
        return JSONResponse({"ok": ok, "keys": _model_keys.get_masked()})

    @app.get("/api/memory/preferences")
    async def list_preferences() -> JSONResponse:
        rows = _longterm.list_by_kind("preference", limit=100)
        return JSONResponse({"preferences": rows})

    @app.delete("/api/memory/preferences/{pref_id}")
    async def delete_preference(pref_id: int) -> JSONResponse:
        # 先按 id 找到内容,再双后端按内容删除(保持关键词/向量一致)
        rows = _longterm.list_by_kind("preference", limit=1000)
        target = next((r for r in rows if r["id"] == pref_id), None)
        if target is None:
            return JSONResponse({"ok": False, "error": "未找到该偏好"}, status_code=404)
        n = _longterm.delete_by_content("preference", target["content"])
        return JSONResponse({"ok": n > 0, "deleted": n})

    @app.get("/api/governance/stats")
    async def governance_stats(days: float = 7.0) -> JSONResponse:
        trace_path = os.path.join(Config.LOG_DIR, "trace.jsonl")
        return JSONResponse(load_stats(trace_path, days=days))

    @app.get("/api/usage")
    async def usage_stats(days: float = 30.0) -> JSONResponse:
        trace_path = os.path.join(Config.LOG_DIR, "trace.jsonl")
        return JSONResponse(load_usage(trace_path, days=days))

    @app.get("/api/agents/roster")
    async def get_roster() -> JSONResponse:
        return JSONResponse({"agents": list_roster_agents(_ROSTER_DIR)})

    @app.get("/api/roundtable/presets")
    async def roundtable_presets() -> JSONResponse:
        from agents.roundtable import AGENT_COLORS, PRESET_PROMPTS

        preset_meta = {
            "pm": {"name": "产品经理", "role": "关注用户需求、产品价值与市场机会"},
            "engineer": {"name": "工程师", "role": "关注技术可行性、实现挑战与系统设计"},
            "risk": {"name": "风险评估师", "role": "发现潜在风险、最坏情况与合规隐患"},
            "creative": {"name": "创意总监", "role": "发散思维，提出创新方案与可能性"},
            "devil": {"name": "魔鬼代言人", "role": "挑战假设，发现讨论中的盲点"},
            "marketing": {"name": "营销专家", "role": "市场定位、用户获取与品牌增长"},
            "trade": {"name": "外贸专员", "role": "国际市场、跨境合规与本地化"},
        }
        presets = []
        for agent_id, prompt in PRESET_PROMPTS.items():
            if agent_id == "custom":
                continue
            meta = preset_meta.get(agent_id, {})
            presets.append({
                "id": agent_id,
                "name": meta.get("name", agent_id),
                "role": meta.get("role", agent_id),
                "system_prompt": prompt,
                "color": AGENT_COLORS.get(agent_id, "#888888"),
            })
        return JSONResponse({"presets": presets})

    @app.get("/api/commands")
    async def get_slash_commands() -> JSONResponse:
        from skills.paths import resolve_skills_dirs
        return JSONResponse({"commands": list_slash_commands(_ROSTER_DIR, resolve_skills_dirs())})

    @app.get("/api/skills")
    async def get_skills() -> JSONResponse:
        from skills.paths import build_skill_registry, resolve_skills_dirs

        reg = build_skill_registry()
        reg.discover()
        project_root = os.path.abspath(resolve_skills_dirs()[0]) if resolve_skills_dirs() else ""
        items = []
        for m in reg.available():
            has_impl = os.path.isfile(os.path.join(m.path, "impl.py"))
            origin = "builtin" if os.path.abspath(m.source_root) == project_root else "user"
            items.append({
                "name": m.name,
                "description": m.description,
                "cmd": f"/{m.name}",
                "risk": m.risk.name,
                "path": m.path,
                "source_root": m.source_root,
                "has_impl": has_impl,
                "origin": origin,
            })
        return JSONResponse({"skills": items})

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        # /ws 能驱动 agent 跑 shell / 写文件,敏感程度等同 /api/*。
        # 本机(loopback)放行,保持本地零配置;非本机连接需 AGENT_API_TOKEN
        # (通过 ?token= 查询参数或 X-Agent-Token 头携带),否则直接拒绝握手。
        client_host = ws.client.host if ws.client else ""
        if not _is_loopback(client_host):
            token = os.environ.get("AGENT_API_TOKEN", "").strip()
            provided = ws.query_params.get("token") or ws.headers.get("x-agent-token", "")
            if not token or not hmac.compare_digest(provided, token):
                await ws.close(code=1008)  # 1008 = policy violation
                return
        await ws.accept()
        channel = WebChannel()
        ws_model: List[Optional[str]] = [None]
        coord_holder: list = []
        rollback_holder: list = []
        bundle_holder: list = []

        def _rebuild_stack(model_id: Optional[str] = None):
            from llm.model_registry import get_model

            mid = model_id or _runtime_cfg.get_model()
            spec = get_model(mid)
            _runtime_cfg.save({"model": mid, "provider": spec.provider})
            c, b = build_core(channel, model=mid)
            coord_holder[:] = [c]
            rollback_holder[:] = [b.rollback]
            bundle_holder[:] = [b]
            ws_model[0] = mid
            return b.agent, b.ctx, b.rollback

        agent, ctx, rollback = _rebuild_stack(ws_model[0])
        coordinator = coord_holder[0]
        session_started_at = time.time()
        # 快照系统头(人设 + 能力清单),切换会话时据此重置上下文。
        header_msgs = list(ctx.messages)

        def _push_status(last_task_seconds: float | None = None) -> None:
            mid = ws_model[0] or _runtime_cfg.get_model()
            emit_status_event(
                channel, agent, ctx, mid, session_started_at, last_task_seconds,
            )

        def serialize_history() -> list:
            out = []
            for m in ctx.messages:
                if m.role.value == "system":
                    continue
                out.append({"role": m.role.value, "content": m.content,
                            "name": m.name})
            return out

        async def bind_and_send_history(session_id: str) -> None:
            ctx.messages = list(header_msgs)
            ctx.store = None
            ctx.bind_session(_session_store, session_id, create=True)
            await ws.send_json({"type": "history",
                                "payload": {"session_id": session_id,
                                            "messages": serialize_history()}})
            _push_status()

        async def sender() -> None:
            while True:
                event = await channel.outbound.get()
                await ws.send_json(to_wire(event))

        def _skill_names() -> set[str]:
            from skills.paths import build_skill_registry
            reg = build_skill_registry()
            reg.discover()
            return {m.name for m in reg.available()}

        def _skill_manifests():
            from skills.paths import build_skill_registry
            reg = build_skill_registry()
            reg.discover()
            return reg.available()

        async def _handle_slash(text: str) -> bool:
            from agents.commands import (
                format_models_help,
                format_skills_help,
                parse_skill_args,
                parse_slash_command,
            )

            nonlocal agent, ctx, rollback
            names = set()
            try:
                from agents.spec import load_specs_from_roster
                names = {s.name for s in load_specs_from_roster(_ROSTER_DIR)}
            except Exception:
                pass
            cmd = parse_slash_command(text, names, _skill_names())
            if cmd.kind == "list_models":
                channel.emit(Event(type=EventType.ASSISTANT_MESSAGE, payload={
                    "text": format_models_help(ws_model[0] or _runtime_cfg.get_model()),
                    "source": "system",
                }))
                return True
            if cmd.kind == "set_model":
                agent, ctx, rollback = _rebuild_stack(cmd.target)
                header_msgs[:] = list(ctx.messages)
                channel.emit(Event(type=EventType.ASSISTANT_MESSAGE, payload={
                    "text": f"已切换模型 → {cmd.target}",
                    "source": "system",
                }))
                return True
            if cmd.kind == "list_skills":
                channel.emit(Event(type=EventType.ASSISTANT_MESSAGE, payload={
                    "text": format_skills_help(_skill_manifests()),
                    "source": "system",
                }))
                return True
            if cmd.kind == "invoke_skill":
                bundle = bundle_holder[0] if bundle_holder else None
                if bundle is None:
                    return False
                cap = bundle.registry.get(f"skill.{cmd.target}")
                if cap is None:
                    channel.emit(Event(type=EventType.ASSISTANT_MESSAGE, payload={
                        "text": f"未找到 skill `{cmd.target}`。输入 /skills 查看列表。",
                        "source": "system",
                    }))
                    return True
                args = parse_skill_args(cmd.target, cmd.task)
                result = await cap.invoke(args, ctx)
                if result.ok:
                    channel.emit(Event(type=EventType.ASSISTANT_MESSAGE, payload={
                        "text": result.output or "(无输出)",
                        "source": f"skill.{cmd.target}",
                    }))
                else:
                    channel.emit(Event(type=EventType.ERROR, payload={
                        "message": result.error or "skill 执行失败",
                    }))
                return True
            return False

        chat_task_holder: list = [None]
        chat_task_gen: list = [0]

        async def run_chat_task(text: str) -> None:
            from channels.task_scope import reset_task_gen, set_task_gen

            chat_task_gen[0] += 1
            gen = chat_task_gen[0]
            scope_token = set_task_gen(gen)
            channel.cancel_pending_approval()
            sid = ctx.session_id or "default"
            t0 = time.time()
            try:
                async with _session_lock(sid):
                    if ctx.session_id:
                        ctx.messages = list(header_msgs)
                        ctx.bind_session(_session_store, ctx.session_id)
                    if await _handle_slash(text):
                        pass
                    else:
                        await coord_holder[0].run(text, ctx, channel.confirm)
                        if _pref_mining_enabled():
                            # 后台沉淀偏好 + 协作日志,均不阻塞回复
                            asyncio.create_task(_mine_preferences(list(ctx.messages)))
                            asyncio.create_task(_consolidate_journal(list(ctx.messages)))
            except asyncio.CancelledError:
                channel.emit(Event(type=EventType.ASSISTANT_MESSAGE, payload={
                    "text": "已停止",
                    "source": "system",
                    "stopped": True,
                }))
                raise
            except Exception as exc:
                channel.emit(Event(type=EventType.ERROR, payload={"message": str(exc)[:500]}))
            finally:
                reset_task_gen(scope_token)
                _push_status(time.time() - t0)
                channel.emit(Event(type=EventType.TASK_DONE, payload={}))

        async def worker() -> None:
            while True:
                text = await channel.receive()
                if text is None:
                    continue
                if chat_task_holder[0] and not chat_task_holder[0].done():
                    chat_task_holder[0].cancel()
                    try:
                        await chat_task_holder[0]
                    except asyncio.CancelledError:
                        pass
                chat_task_holder[0] = asyncio.create_task(run_chat_task(text))
                try:
                    await chat_task_holder[0]
                except asyncio.CancelledError:
                    pass

        rt_task_holder: list = [None]
        rt_user_queue: asyncio.Queue = asyncio.Queue()
        debate_task_holder: list = [None]

        async def run_roundtable(payload: dict) -> None:
            from agents.roundtable import AdvancedRoundtable
            from llm.factory import build_llm as _build_llm

            rt_session_id = str(payload.get("session_id") or f"rt-{int(time.time() * 1000)}")
            topic = str(payload.get("topic", "")).strip()
            record: dict = {
                "topic": topic,
                "goal": str(payload.get("goal", "")).strip(),
                "max_turns": payload.get("max_turns", 12),
                "mode": payload.get("mode", "brainstorm"),
                "messages": [],
                "summary": "",
                "configs": payload.get("agents", []),
                "stopped": "",
                "turns": 0,
            }

            def _capture_rt_event(evt: dict) -> None:
                et = evt.get("type")
                if et == "rt_message":
                    record["messages"].append({
                        "agent_id": evt.get("agent_id"),
                        "agent_name": evt.get("agent_name"),
                        "role": evt.get("role"),
                        "content": evt.get("content"),
                        "msg_type": evt.get("msg_type"),
                        "turn": evt.get("turn"),
                        "agent_color": evt.get("agent_color"),
                        "phase": evt.get("phase"),
                    })
                elif et == "rt_summary":
                    record["summary"] = evt.get("content", "") or record["summary"]
                elif et == "rt_done":
                    record["stopped"] = evt.get("stopped", "") or record["stopped"]
                    record["turns"] = evt.get("turns", record["turns"])

            def _persist_roundtable() -> None:
                if not record["messages"] and not record["summary"]:
                    return
                title = topic[:40] if topic else "圆桌会议"
                try:
                    _session_store.save_roundtable(rt_session_id, title, record)
                except Exception:
                    pass

            # 显式传 provider,不再改全局 Config/env(并发会话互不串改)。
            def llm_factory(model: str):
                return _build_llm(model=model)

            rt = AdvancedRoundtable(llm_factory, max_turns=payload.get("max_turns", 12))

            async def on_event(evt: dict):
                _capture_rt_event(evt)
                out = evt
                if evt.get("type") == "rt_done":
                    out = {**evt, "session_id": rt_session_id}
                try:
                    await ws.send_json(out)
                except Exception:
                    pass

            # 证据接入:开启时提供一个含 web.search 的最小 registry 供圆桌检索锚定。
            rt_registry = None
            if payload.get("enable_evidence"):
                from capabilities.base import CapabilityRegistry
                from capabilities.tools.web import WebSearch
                rt_registry = CapabilityRegistry([WebSearch()])

            try:
                result = await rt.run(
                    configs=payload.get("agents", []),
                    topic=topic,
                    on_event=on_event,
                    max_turns=payload.get("max_turns", 12),
                    enable_interrupt=payload.get("enable_interrupt", True),
                    user_queue=rt_user_queue,
                    mode=payload.get("mode", "brainstorm"),
                    goal=record["goal"],
                    registry=rt_registry,
                    enable_evidence=bool(payload.get("enable_evidence", False)),
                    enable_judge=bool(payload.get("enable_judge", False)),
                )
                record["stopped"] = result.get("stopped", record["stopped"])
                record["turns"] = result.get("turns", record["turns"])
                if result.get("verdict"):
                    record["verdict"] = result["verdict"]
                if not record["summary"] and result.get("summary"):
                    record["summary"] = result["summary"]
            except asyncio.CancelledError:
                record["stopped"] = record["stopped"] or "用户停止"
                await ws.send_json({
                    "type": "rt_done",
                    "turns": record["turns"],
                    "stopped": "用户停止",
                    "session_id": rt_session_id,
                })
            except Exception as e:
                await ws.send_json({"type": "error", "payload": {"message": str(e)}})
            finally:
                _persist_roundtable()

        async def run_debate(payload: dict) -> None:
            from agents.debate import Debate
            from llm.factory import build_llm as _build_llm

            def llm_factory(model: str):
                return _build_llm(model=model)

            debate = Debate(llm_factory, max_rounds=payload.get("max_rounds", 2))
            prov = payload.get("model") or payload.get("provider") or ws_model[0] or _runtime_cfg.get_model()

            async def on_event(evt: dict):
                try:
                    await ws.send_json(evt)
                except Exception:
                    pass

            try:
                await debate.run(
                    payload.get("topic", ""),
                    pro_model=payload.get("pro_model", prov),
                    con_model=payload.get("con_model", prov),
                    moderator_model=payload.get("moderator_model", prov),
                    on_event=on_event,
                )
            except asyncio.CancelledError:
                await ws.send_json({"type": "debate_done", "rounds": 0, "stopped": "用户停止"})
            except Exception as e:
                await ws.send_json({"type": "error", "payload": {"message": str(e)}})

        sender_task = asyncio.create_task(sender())
        worker_task = asyncio.create_task(worker())
        try:
            while True:
                msg = await ws.receive_json()
                if msg.get("type") == "init":
                    from llm.model_registry import normalize_model_id

                    if "model" in msg:
                        ws_model[0] = normalize_model_id(str(msg.get("model")))
                    elif "provider" in msg:
                        ws_model[0] = normalize_model_id(str(msg.get("provider")))
                    agent, ctx, rollback = _rebuild_stack(ws_model[0])
                    coordinator = coord_holder[0]
                    header_msgs = list(ctx.messages)
                    await bind_and_send_history(msg.get("session_id", "default"))
                elif msg.get("type") == "rollback":
                    tid = msg.get("trace_id") or getattr(agent, "last_trace_id", "")
                    rb = rollback_holder[0] if rollback_holder else rollback
                    notes = rb.rollback(tid) if rb and tid else []
                    await ws.send_json({"type": "rollback_result",
                                        "payload": {"ok": bool(notes), "notes": notes}})
                elif msg.get("type") == "user":
                    channel.feed_user(msg.get("text", ""))
                elif msg.get("type") == "approval":
                    approved = bool(msg.get("approved"))
                    if approved and msg.get("grant_task", True):
                        ctx.task_auto_approve = True
                    cap_grant = msg.get("grant_capability")
                    if cap_grant:
                        ctx.grant_capability(str(cap_grant))
                    tg = msg.get("task_gen")
                    channel.feed_approval(
                        approved,
                        task_gen=int(tg) if tg is not None else None,
                    )
                elif msg.get("type") == "roundtable_start":
                    if rt_task_holder[0] and not rt_task_holder[0].done():
                        rt_task_holder[0].cancel()
                    while not rt_user_queue.empty():
                        try:
                            rt_user_queue.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                    rt_task_holder[0] = asyncio.create_task(run_roundtable(msg))
                elif msg.get("type") == "roundtable_user_speak":
                    text = str(msg.get("text", "")).strip()
                    if text:
                        await rt_user_queue.put(text)
                elif msg.get("type") == "roundtable_stop":
                    if rt_task_holder[0] and not rt_task_holder[0].done():
                        rt_task_holder[0].cancel()
                elif msg.get("type") == "debate_start":
                    if debate_task_holder[0] and not debate_task_holder[0].done():
                        debate_task_holder[0].cancel()
                    debate_task_holder[0] = asyncio.create_task(run_debate(msg))
                elif msg.get("type") == "debate_stop":
                    if debate_task_holder[0] and not debate_task_holder[0].done():
                        debate_task_holder[0].cancel()
                elif msg.get("type") == "task_stop":
                    if chat_task_holder[0] and not chat_task_holder[0].done():
                        chat_task_holder[0].cancel()
        except WebSocketDisconnect:
            pass
        finally:
            sender_task.cancel()
            worker_task.cancel()
            if rt_task_holder[0] and not rt_task_holder[0].done():
                rt_task_holder[0].cancel()
            if debate_task_holder[0] and not debate_task_holder[0].done():
                debate_task_holder[0].cancel()
            if chat_task_holder[0] and not chat_task_holder[0].done():
                chat_task_holder[0].cancel()

    return app


app = create_app()


def run() -> None:
    """Web 服务入口(console_scripts: myagent-web)。默认绑 127.0.0.1:8000。

    可用环境变量覆盖:AGENT_WEB_HOST / AGENT_WEB_PORT。
    ⚠ 对外暴露(host=0.0.0.0)前请设置 AGENT_API_TOKEN(见 /api/* 鉴权中间件)。
    """
    import os as _os
    root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    _os.environ.setdefault("AGENT_PROJECT_ROOT", root)
    try:
        _os.chdir(root)
    except OSError:
        pass
    try:
        import uvicorn
    except ImportError:
        raise SystemExit("需要 uvicorn:请先安装 `pip install 'my-agent[web]'` 或 `pip install uvicorn`。")
    host = _os.environ.get("AGENT_WEB_HOST", "127.0.0.1")
    port = int(_os.environ.get("AGENT_WEB_PORT", "8000"))
    print(f"Web 聊天 → http://{host}:{port}  (Ctrl+C 停止)")
    uvicorn.run(app, host=host, port=port)
