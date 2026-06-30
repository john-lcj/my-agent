"""FastAPI 服务 —— /ws 流式聊天 + 邮件渠道。

端点一览:
  GET  /           Web 前端(index.html)
  WS   /ws         WebSocket 聊天(流式 + 确认卡片)

外部渠道:仅保留邮件(EMAIL_USER 非空 => 启用,后台 IMAP 轮询)。
其余 IM 渠道(QQ/微信/Slack/Telegram)已移除——日常使用走「手机经 Tailscale
直连本机 Web UI」,定时任务产物通过邮件投递。

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
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

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
from memory.feedback_store import FeedbackStore
from scheduler.store import ScheduledTask, TaskStore
from scheduler.scheduler import Scheduler
from server.events import to_wire
from server.governance_stats import load_stats
from server.usage_stats import load_usage
from server.commands_api import list_slash_commands
from server.runtime_config import RuntimeConfigStore
from server.model_keys import ModelKeyStore, PROVIDER_KEY_ENV

# 后台任务函数（已拆分到 async_tasks.py，通过延迟导入访问本模块单例）
from server.async_tasks import (
    _run_scheduled_task, _run_ext_channel,
    _daemon_worker, _daemon_inbox_watch,
    _daemon_monitor_watch, _register_mcp_tools,
)

_FRONTEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")

# ── 跨连接共享的单例:持久化会话、长期记忆、人设、频道配置、定时任务 ──────────
_session_store = SessionStore(db_path=f"{Config.LOG_DIR}/sessions.db")
_feedback_store = FeedbackStore(db_path=f"{Config.LOG_DIR}/feedback.db")
_session_locks: dict[str, asyncio.Lock] = {}


def _session_lock(session_id: str) -> asyncio.Lock:
    lock = _session_locks.get(session_id)
    if lock is None:
        if len(_session_locks) > 1000:
            for k in [k for k, v in list(_session_locks.items())
                      if not v.locked() and k != session_id]:
                _session_locks.pop(k, None)
        lock = asyncio.Lock()
        _session_locks[session_id] = lock
    return lock


_START_TS = time.time()  # 进程启动时刻,供 /api/stats 计算 uptime
if (os.environ.get("AGENT_LLM_PROVIDER", "").strip().lower() != "mock"
        and (os.environ.get("AGENT_PROVIDER", "").strip().lower() != "mock")):
    os.environ.setdefault("AGENT_JUDGE_MODEL", "deepseek-v4-pro")
    os.environ.setdefault("AGENT_REFLECT_MODEL", "deepseek-v4-pro")
_longterm = build_longterm(Config.LOG_DIR)
_persona = load_persona()
from memory.template_store import TemplateStore
from memory.secrets_vault import SecretsVault
_template_store = TemplateStore(db_path=f"{Config.LOG_DIR}/templates.db")
try:
    from core.office_templates import BUILTIN_OFFICE_TEMPLATES
    _template_store.seed_once(BUILTIN_OFFICE_TEMPLATES)
except Exception as _te:
    print(f"[templates] 内置模板种入跳过: {_te}")
from memory.share_store import ShareStore
_share_store = ShareStore(path=f"{Config.LOG_DIR}/shares.json")
from memory.mission_store import MissionStore
_mission_store = MissionStore(db_path=f"{Config.LOG_DIR}/missions.db")


async def _mission_execute(prompt: str) -> str:
    from core.types import Identity
    actor = Identity(subject_id="mission", agent_name="main", channel="mission")
    agent, ctx = _build_scheduler_agent(actor)
    ctx.coworker = True
    ctx.mem_scope = "mission|"

    async def _deny(call, decision, reason=""):
        return False

    return await agent.run(prompt, ctx, _deny)


def _mission_notify(mission: dict, reason: str) -> None:
    import asyncio
    goal = mission.get("goal", "")
    mid = mission.get("id", "")
    subject = f"[Mission 卡住] {goal[:40]}"
    body = (f"任务「{goal}」卡住了,需要你:\n\n{reason}\n\n"
            f"补充后在 Captain 的「任务」面板点该任务的「补充并恢复」继续(mission id: {mid})。")
    try:
        asyncio.create_task(_deliver_result("email", "", subject, body))
    except Exception:
        pass


def _start_mission(mid: str) -> None:
    import asyncio
    from core.mission_runner import run_mission
    asyncio.create_task(run_mission(_mission_store, mid, _mission_execute,
                                    notify=_mission_notify))


def _resume_mission(mid: str, info: str = "") -> None:
    import asyncio
    from core.mission_runner import resume_mission
    asyncio.create_task(resume_mission(_mission_store, mid, _mission_execute,
                                       info=info, notify=_mission_notify))


try:
    _vault = SecretsVault(db_path=f"{Config.LOG_DIR}/vault.db",
                          key_file=f"{Config.LOG_DIR}/.vault_key")
except Exception as _ve:
    _vault = None
    print(f"[server] 凭据保险库初始化失败: {_ve}")
_runtime_cfg = RuntimeConfigStore(path=f"{Config.LOG_DIR}/runtime.json")
if not os.environ.get("VISION_MODEL", "").strip():
    _vm = (_runtime_cfg.load().get("vision_model") or "").strip()
    if _vm:
        os.environ["VISION_MODEL"] = _vm
_ROSTER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agents", "roster")
_channel_cfg = ChannelConfigStore(path=f"{Config.LOG_DIR}/channels.json")
_model_keys = ModelKeyStore(path=f"{Config.LOG_DIR}/model_keys.json")
_task_store = TaskStore(db_path=f"{Config.LOG_DIR}/tasks.db")
from memory.project_store import ProjectStore
_project_store = ProjectStore(path=f"{Config.LOG_DIR}/projects.json")
_scheduler_holder: list = [None]   # [Scheduler|None]，lifespan 启动后填充

# ── 外部渠道注册表(启动时按 .env 填充)───────────────────────────────────────
_ext_channels: dict[str, object] = {}
_ext_coordinators: dict[str, object] = {}
_ext_templates: dict[str, object] = {}


def _resolve_in_workspace(path: str) -> tuple:
    raw = (path or "").strip()
    if not raw:
        return False, "", "缺少 path"
    root = os.environ.get("AGENT_WORKSPACE_ROOT", "").strip()
    if root:
        root = os.path.realpath(os.path.expanduser(root))
    if not os.path.isabs(raw):
        base = root or os.getcwd()
        raw = os.path.join(base, raw)
    real = os.path.realpath(os.path.expanduser(raw))
    low = real.lower()
    if any(s in low for s in (".env", ".ssh", "id_rsa", "credentials", "model_keys.json")):
        return False, "", "敏感路径,拒绝读取"
    if root:
        if real != root and not real.startswith(root + os.sep):
            return False, "", "路径在工作区之外"
    return True, real, ""


def _pref_mining_enabled() -> bool:
    if not Config.PREF_MINING:
        return False
    return (_runtime_cfg.get_model() or "").lower() != "mock"


async def _mine_preferences(messages: list) -> None:
    try:
        from llm.factory import build_llm
        from memory.preference_miner import PreferenceMiner
        miner = PreferenceMiner(build_llm(model=_runtime_cfg.get_model()), _longterm)
        stored = await miner.mine(messages)
        if stored:
            print(f"[pref] 沉淀偏好 {len(stored)} 条: {stored}")
    except Exception:
        pass


async def _mine_experience(messages: list) -> None:
    try:
        from llm.factory import build_llm
        from memory.experience_miner import ExperienceMiner
        miner = ExperienceMiner(build_llm(model=_runtime_cfg.get_model()), _longterm)
        stored = await miner.mine(messages)
        if stored:
            print(f"[exp] 沉淀经验 {len(stored)} 条: {stored}")
    except Exception:
        pass


async def _consolidate_journal(messages: list) -> None:
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
        max_steps=_runtime_cfg.get_max_steps(),
    )
    return coordinator, bundle


def _build_ext_stack(channel):
    return build_coordinator_stack(
        channel.identity(),
        profile="external",
        longterm=_longterm,
        persona=_persona,
        event_sink=channel.emit,
    )


def _build_scheduler_agent(actor: Identity, model: str | None = None):
    bundle = build_agent_bundle(
        actor,
        profile="interactive",
        longterm=_longterm,
        persona=_persona,
        with_rollback=False,
        model=model or None,
    )
    return bundle.agent, bundle.ctx


async def _deliver_result(channel: str, to: str, subject: str, body: str) -> None:
    ch = _ext_channels.get(channel)
    if ch is None:
        print(f"[scheduler] 渠道 {channel} 未启用,跳过投递")
        return
    if channel == "email":
        target = to or ch.user
        await ch._send_email(target, subject, body, attachments=_extract_artifacts(body))


def _extract_artifacts(text: str) -> list:
    import re as _re
    paths: list[str] = []
    for m in _re.findall(r"[\w./~-]+\.(?:md|html|xlsx|xls|pdf|csv|docx|txt|json)", text or ""):
        p = os.path.expanduser(m)
        if not os.path.isabs(p):
            p = os.path.join(os.environ.get("AGENT_WORKSPACE_ROOT", "") or os.getcwd(), p)
        if os.path.isfile(p) and p not in paths:
            paths.append(p)
    return paths[:5]


def _enable_channel(name: str) -> bool:
    if name == "email" and os.environ.get("EMAIL_USER"):
        from channels.email_channel import EmailChannel
        ch = EmailChannel()
        coordinator, bundle = _build_ext_stack(ch)
        _ext_channels["email"] = ch
        _ext_coordinators["email"] = coordinator
        _ext_templates["email"] = bundle.ctx
        return True
    return False


async def _enable_channel_async(name: str) -> bool:
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


# ── 后台任务守护:队列 + 投递入口(文件夹监听 / HTTP)─────────────────────────
import uuid as _uuid

_task_queue: "asyncio.Queue | None" = None
_daemon_results: dict[str, dict] = {}
_DAEMON_MAX_RESULTS = 200


def _daemon_enqueue(text: str, source: str = "api", mode: str = "coworker") -> str:
    tid = _uuid.uuid4().hex[:12]
    _daemon_results[tid] = {
        "id": tid, "status": "queued", "source": source, "mode": mode,
        "text": (text or "")[:500], "result": "", "error": "",
        "created": time.time(), "finished": 0.0,
    }
    if _task_queue is not None:
        _task_queue.put_nowait((tid, text, mode, source))
    if len(_daemon_results) > _DAEMON_MAX_RESULTS:
        for k in sorted(_daemon_results, key=lambda x: _daemon_results[x]["created"])[:50]:
            _daemon_results.pop(k, None)
    return tid


# ── 主动反思引擎:按目标自省,边界内全自动地做/提醒,结果发邮箱 ────────────────
_PATROL_PROMPT = """你是主人的主动助手,现在在后台自省一次(无人值守、可全自动执行,硬边界仍会拦)。
下面是主人的长期目标与近况:

{context}

先用 suggest.list 看已经发过哪些建议(别重复)。然后判断:现在有没有"值得主动替主人做或提醒"的事?
- 能自己安全完成的(查资料/整理/读文件/盯进度)就直接做掉,把有价值的发现用 suggest.add(kind=idea)发给主人。
- 想到值得做但该由主人拍板的(尤其涉及外发/花钱/不可逆),用 suggest.add 发成建议:text 写清"是什么、为什么值得做",action 写"主人点接受后要执行的指令"。
- 学到值得长期记住的经验,用 memory.remember 记下。
- 没有值得打扰主人的事:**只回复一个字「无」**,不要硬编。
现在开始。"""

_DIGEST_PROMPT = """你是主人的主动助手,现在做每日主动规划。结合其长期目标与近况:

{context}

请主动思考并用 suggest.add 发出建议(每条:text=给主人看的一句话,action=接受后要执行的指令,kind 见下):
1) plan:基于长期目标,提出"今天最值得做的 1~2 件事",并问主人要不要做;
2) resume:对【未尽事项】里每个还没做完的,**自己想一个新思路/新切入点**,发成"这个我有个新思路 X,要不要试试"(action 写按新思路续做的指令);
3) skill:如果发现某类任务反复出现,建议"固化成一个 skill 复用"(action 写用 skill.scaffold 固化的指令);
4) retro:如最近完成过任务,给一条简短复盘(做得怎样、下次怎么更好),并用 memory.remember 把经验记进深度记忆。
发完建议后,再写一段 200 字内的简报正文(今天的重点 + 你发了哪些建议),作为最终回复(会邮件给主人)。"""


def _proactive_context() -> str:
    import glob
    import json as _json
    parts = [f"【当前时间】{time.strftime('%Y-%m-%d %H:%M')}"]
    try:
        from memory.goals_store import GoalsStore
        goals = GoalsStore(path=f"{Config.LOG_DIR}/goals.json").active_texts()
    except Exception:
        goals = []
    parts.append("【长期目标/关注点】\n"
                 + ("\n".join("- " + g for g in goals) if goals
                    else "(主人尚未登记长期目标;可在简报里建议他登记几条)"))
    try:
        prefs = _longterm.list_by_kind("preference", limit=8)
        if prefs:
            parts.append("【已知偏好】\n" + "\n".join("- " + p.get("content", "") for p in prefs[:8]))
    except Exception:
        pass
    undone: list[str] = []
    for f in glob.glob(os.path.join(Config.LOG_DIR, "checkpoints", "*.json")):
        try:
            d = _json.load(open(f, encoding="utf-8"))
            for s in d.get("steps", []):
                if s.get("status") not in ("done",) and s.get("text"):
                    undone.append(s["text"])
        except Exception:
            pass
    if undone:
        parts.append("【未尽事项(此前没做完的)】\n" + "\n".join("- " + u for u in undone[:8]))
    return "\n\n".join(parts)


async def _proactive_deliver(source: str, body: str) -> None:
    body = (body or "").strip()
    if source == "proactive":
        stripped = body.replace("。", "").replace(".", "").strip()
        if len(body) < 6 or stripped in ("无", "暂无", "没有", "无需打扰"):
            return
    if not body:
        return
    to = os.environ.get("AGENT_BRIEFING_TO", "").strip() or os.environ.get("EMAIL_USER", "").strip()
    if not to:
        return
    subject = "Captain · 每日主动简报" if source == "digest" else "Captain · 主动汇报"
    try:
        await _deliver_result("email", to, subject, body)
    except Exception as e:
        print(f"[proactive] 投递失败: {e}")


async def _proactive_patrol() -> None:
    interval = float(os.environ.get("AGENT_PROACTIVE_PATROL_SEC", "3600"))
    while True:
        await asyncio.sleep(interval)
        try:
            _daemon_enqueue(_PATROL_PROMPT.format(context=_proactive_context()),
                            source="proactive", mode="coworker")
        except Exception as e:
            print(f"[proactive] 巡检异常: {e}")


async def _proactive_digest() -> None:
    at = (os.environ.get("AGENT_DIGEST_AT", "").strip()
          or os.environ.get("AGENT_BRIEFING_AT", "08:00"))
    last_day = ""
    while True:
        await asyncio.sleep(40)
        now = time.localtime()
        if time.strftime("%H:%M", now) == at and time.strftime("%Y-%m-%d", now) != last_day:
            last_day = time.strftime("%Y-%m-%d", now)
            try:
                _daemon_enqueue(_DIGEST_PROMPT.format(context=_proactive_context()),
                                source="digest", mode="coworker")
            except Exception as e:
                print(f"[proactive] 简报异常: {e}")


# ── 鉴权辅助(模块级,供 create_app 中间件 + register_ws 使用)──────────────────
import re as _re_mod
_LOCAL_IP_RE = _re_mod.compile(r'^127\.\d+\.\d+\.\d+$')


def _is_loopback(host: str) -> bool:
    if host in ("localhost", "", "testclient"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _is_proxied(headers) -> bool:
    """是否经反向代理/隧道(Cloudflare Tunnel、ngrok 等)进来。"""
    return bool(headers.get("cf-ray") or headers.get("cf-connecting-ip")
                or headers.get("x-forwarded-for") or headers.get("x-forwarded-host"))


def _is_safe_origin(origin: str, host_header: str) -> bool:
    """允许同源或本机 origin；拒绝跨站页面发起的写操作。"""
    if not origin:
        return True
    try:
        from urllib.parse import urlparse
        parsed = urlparse(origin)
        origin_host = (parsed.hostname or "").lower()
        if _is_loopback(origin_host):
            return True
        request_host = (host_header or "").split(":")[0].lower()
        return bool(request_host and origin_host == request_host)
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
def create_app():
    load_env()

    @asynccontextmanager
    async def _lifespan(_app: FastAPI):
        for name in ("email",):
            try:
                ok = await _enable_channel_async(name) if name == "email" else _enable_channel(name)
                if ok:
                    print(f"[server] {name} 渠道已启动")
            except Exception as e:
                print(f"[server] {name} 渠道启动失败: {e}")

        _scheduler_holder[0] = Scheduler(_task_store, _run_scheduled_task, _deliver_result)
        _scheduler_holder[0].start()
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

        await _register_mcp_tools()

        global _task_queue
        _task_queue = asyncio.Queue()
        asyncio.create_task(_daemon_worker())
        if os.environ.get("AGENT_INBOX_WATCH", "1") != "0":
            asyncio.create_task(_daemon_inbox_watch())
        if os.environ.get("AGENT_MONITOR_WATCH", "1") != "0":
            asyncio.create_task(_daemon_monitor_watch())
        print("[server] 后台任务守护已启动(收件箱监听 + 主动监控 + HTTP /api/task)")
        if os.environ.get("AGENT_PROACTIVE", "0") != "0":
            asyncio.create_task(_proactive_patrol())
            asyncio.create_task(_proactive_digest())
            print("[server] 主动反思引擎已启动(按小时巡检 + 每日主动简报 → 邮箱)")

        yield
        if _scheduler_holder[0] is not None:
            _scheduler_holder[0].stop()

    app = FastAPI(title="my-agent", lifespan=_lifespan)

    # ── CORS ──────────────────────────────────────────────────────────────────
    from fastapi.middleware.cors import CORSMiddleware
    _allowed_origins = [
        "http://localhost:8000", "http://127.0.0.1:8000",
        "http://localhost",      "http://127.0.0.1",
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Host 头校验 ────────────────────────────────────────────────────────────
    def _host_is_external(h: str) -> bool:
        if not h or h in ("localhost", "::1"):
            return False
        if _LOCAL_IP_RE.match(h):
            return False
        return "." in h

    @app.middleware("http")
    async def _host_guard(request: Request, call_next):
        host_header = request.headers.get("host", "").split(":")[0].lower()
        if _host_is_external(host_header):
            return JSONResponse(
                {"error": "forbidden", "detail": "Host 头不合法，拒绝请求"},
                status_code=403,
            )
        return await call_next(request)

    # ── 控制面鉴权 ─────────────────────────────────────────────────────────────
    @app.middleware("http")
    async def _api_auth(request: Request, call_next):
        if request.url.path.startswith("/api/"):
            client = request.client.host if request.client else ""
            _DEFAULT_TOKEN = "change-me-to-random-string"
            _DEFAULT_AUTH_SECRET = "captain-dev-secret-change-me-in-prod"
            if request.method not in ("GET", "HEAD", "OPTIONS"):
                origin = request.headers.get("origin", "")
                sec_fetch = request.headers.get("sec-fetch-site", "").lower()
                if origin and not _is_safe_origin(origin, request.headers.get("host", "")):
                    return JSONResponse(
                        {"error": "csrf_blocked",
                         "detail": "跨站请求被拒绝。"},
                        status_code=403,
                    )
                if sec_fetch in {"cross-site", "none"}:
                    return JSONResponse(
                        {"error": "csrf_blocked",
                         "detail": "跨站请求被拒绝。"},
                        status_code=403,
                    )
            if _is_proxied(request.headers) or not _is_loopback(client):
                token = os.environ.get("AGENT_API_TOKEN", "").strip()
                if not token or token == _DEFAULT_TOKEN:
                    return JSONResponse(
                        {"error": "insecure_config",
                         "detail": "检测到远程访问但 AGENT_API_TOKEN 仍为默认值，请在 .env 中设置随机密钥后重启。"},
                        status_code=503,
                    )
                auth_secret = os.environ.get("AUTH_SECRET", "").strip()
                if (request.method not in ("GET", "HEAD", "OPTIONS")
                        and (not auth_secret or auth_secret == _DEFAULT_AUTH_SECRET)):
                    return JSONResponse(
                        {"error": "insecure_config",
                         "detail": "检测到远程访问但 AUTH_SECRET 仍为默认值，请在 .env 中设置随机密钥后重启。"},
                        status_code=503,
                    )
                provided = request.headers.get("x-agent-token", "")
                if not hmac.compare_digest(provided, token):
                    return JSONResponse(
                        {"error": "unauthorized",
                         "detail": "远程访问 /api/* 需设置 AGENT_API_TOKEN 并在 X-Agent-Token 头携带。"},
                        status_code=401,
                    )
        return await call_next(request)

    # ── 路由注册 ───────────────────────────────────────────────────────────────
    from server.routers.channels import register_channels, register_tasks
    register_channels(app, _channel_cfg, _ext_channels, _enable_channel, _enable_channel_async)
    register_tasks(app, _task_store, _scheduler_holder, _daemon_enqueue, _daemon_results)

    from server.routers.secrets_api import register_secrets
    register_secrets(app, _vault)

    from server.routers.voice import register_voice
    register_voice(app)

    from server.routers.writing import register_writing
    register_writing(app)

    from server.routers.license import register_license
    register_license(app)

    from server.routers.profile import register_profile
    register_profile(app)

    from server.routers.system import register_system
    register_system(app, _task_store, _template_store, _vault, _ext_channels,
                    _scheduler_holder, _daemon_results, _START_TS)

    from server.routers.backup import register_backup
    register_backup(app)

    from server.routers.sessions import register_sessions
    register_sessions(app, _session_store)

    from server.routers.models import register_models
    register_models(app, _runtime_cfg, _model_keys, _longterm)

    from server.routers.projects import register_projects
    register_projects(app, _project_store, _session_store)

    from server.routers.artifacts import register_artifacts
    register_artifacts(app, _resolve_in_workspace)

    from server.routers.misc import register_misc
    register_misc(app, _ROSTER_DIR)

    # ── 已有路由(此前已拆出,保持不变)────────────────────────────────────────
    from server.routers.templates import register_templates
    register_templates(app, _template_store)

    from server.routers.monitors import register_monitors
    register_monitors(app)

    from server.routers.goals import register_goals
    register_goals(app)

    from server.routers.suggestions import register_suggestions
    register_suggestions(app, _daemon_enqueue)

    from server.routers.mission import register_missions
    register_missions(app, _mission_store, _start_mission, _resume_mission)

    from server.routers.preview import register_preview
    register_preview(app, _resolve_in_workspace)

    from server.routers.frontend import register_frontend
    register_frontend(app, _FRONTEND)

    # ── 保留在 create_app() 闭包的端点 ────────────────────────────────────────
    # /api/feedback 必须留在闭包内:测试通过 appmod._feedback_store = ... 打桩
    @app.post("/api/feedback")
    async def post_feedback(request: Request) -> JSONResponse:
        body = await request.json()
        sid = str(body.get("session_id", "")).strip()
        key = str(body.get("msg_key", "")).strip()
        try:
            rating = int(body.get("rating", 0))
        except (TypeError, ValueError):
            rating = 0
        if not sid or not key or rating not in (0, 1, -1):
            return JSONResponse({"ok": False, "error": "参数无效"}, status_code=400)
        _feedback_store.upsert(sid, key, rating)
        return JSONResponse({"ok": True, "rating": rating})

    @app.get("/api/feedback")
    async def get_feedback(session_id: str = "", msg_key: str = "") -> JSONResponse:
        sid = (session_id or "").strip()
        key = (msg_key or "").strip()
        if not sid or not key:
            return JSONResponse({"ok": False, "error": "缺少参数"}, status_code=400)
        r = _feedback_store.get(sid, key)
        return JSONResponse({"ok": True, "rating": r})

    @app.get("/api/proactive/preview")
    async def proactive_preview() -> JSONResponse:
        return JSONResponse({"context": _proactive_context(),
                             "enabled": os.environ.get("AGENT_PROACTIVE", "0") != "0"})

    @app.get("/healthz")
    async def healthz() -> JSONResponse:
        return JSONResponse({
            "ok": True,
            "channels": list(_ext_channels.keys()),
            "tasks": len(_task_store.list()),
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        })

    @app.get("/manifest.json")
    async def manifest() -> JSONResponse:
        return JSONResponse({
            "name": "Captain", "short_name": "Captain",
            "start_url": "/", "display": "standalone",
            "background_color": "#0d0d0d", "theme_color": "#0d0d0d",
            "description": "你的私人多智能体助理",
        })

    # ── WebSocket 聊天 ─────────────────────────────────────────────────────────
    from server.routers.ws_chat import register_ws
    register_ws(app, _is_loopback, _is_proxied)

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


if __name__ == "__main__":
    run()
