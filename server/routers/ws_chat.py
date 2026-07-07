"""WebSocket 聊天端点 (从 app.py 抽出，行为不变)。

所有对 server.app 模块级单例的访问通过延迟导入完成，避免循环引用。
"""
from __future__ import annotations
import asyncio
import hmac
import os
import time
from typing import List, Optional

from fastapi import WebSocket, WebSocketDisconnect

from channels.web import WebChannel
from core.types import Event, EventType, Role
from core.status_bar import emit_status_event
from server.events import to_wire


def register_ws(app, is_loopback, is_proxied) -> None:
    """注册 /ws 端点。is_loopback 和 is_proxied 由 create_app() 传入（避免移动这两个辅助函数）。"""

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket) -> None:
        # 延迟导入 server.app 的模块级单例（两个模块都完全加载后才会执行本函数）
        import server.app as _sa

        client_host = ws.client.host if ws.client else ""
        await ws.accept()
        requires_auth = is_proxied(ws.headers) or not is_loopback(client_host)
        if requires_auth:
            token = os.environ.get("AGENT_API_TOKEN", "").strip()
            provided = ws.headers.get("x-agent-token", "") or ws.query_params.get("token", "")
            if not provided:
                try:
                    first = await asyncio.wait_for(ws.receive_json(), timeout=5)
                except Exception:
                    await ws.close(code=1008)
                    return
                if first.get("type") == "auth":
                    provided = str(first.get("token") or "")
                else:
                    await ws.close(code=1008)
                    return
            if not token or not hmac.compare_digest(provided, token):
                await ws.close(code=1008)
                return

        channel = WebChannel()
        ws_model: List[Optional[str]] = [None]
        ws_mode: list = [""]
        coord_holder: list = []
        rollback_holder: list = []
        bundle_holder: list = []

        def _rebuild_stack(model_id: Optional[str] = None):
            from llm.model_registry import get_model
            mid = model_id or _sa._runtime_cfg.get_model()
            spec = get_model(mid)
            _sa._runtime_cfg.save({"model": mid, "provider": spec.provider})
            c, b = _sa.build_core(channel, model=mid)
            coord_holder[:] = [c]
            rollback_holder[:] = [b.rollback]
            bundle_holder[:] = [b]
            ws_model[0] = mid
            return b.agent, b.ctx, b.rollback

        agent, ctx, rollback = _rebuild_stack(ws_model[0])
        coordinator = coord_holder[0]
        session_started_at = time.time()
        header_msgs = list(ctx.messages)

        def _push_status(last_task_seconds: float | None = None) -> None:
            mid = ws_model[0] or _sa._runtime_cfg.get_model()
            emit_status_event(channel, agent, ctx, mid, session_started_at, last_task_seconds)

        def serialize_history() -> list:
            sid = ctx.session_id
            if sid and _sa._session_store.session_exists(sid):
                return _serialize_session_messages(sid)
            out = []
            for m in ctx.messages:
                if m.role.value == "system":
                    continue
                out.append({"role": m.role.value, "content": m.content, "name": m.name})
            return out

        def _serialize_session_messages(session_id: str) -> list:
            out = []
            for row in _sa._session_store.list_messages_meta(session_id):
                out.append({"id": row["id"], "role": row["role"], "content": row["content"],
                             "name": row.get("name"), "ts": row.get("ts")})
            return out

        async def _reload_ctx_from_db(session_id: str) -> None:
            ctx.messages = list(header_msgs)
            ctx.store = None
            ctx.bind_session(_sa._session_store, session_id, create=False)

        async def _push_history(session_id: str) -> None:
            await ws.send_json({"type": "history",
                                "payload": {"session_id": session_id,
                                            "messages": _serialize_session_messages(session_id)}})

        async def bind_and_send_history(session_id: str) -> None:
            ctx.messages = list(header_msgs)
            ctx.store = None
            ctx.bind_session(_sa._session_store, session_id, create=False)
            await ws.send_json({"type": "history",
                                "payload": {"session_id": session_id,
                                            "messages": serialize_history()}})
            _push_status()

        async def send_history_peek(session_id: str) -> None:
            await ws.send_json({"type": "history",
                                "payload": {"session_id": session_id,
                                            "messages": _serialize_session_messages(session_id)}})
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
                format_models_help, format_skills_help,
                parse_skill_args, parse_slash_command,
            )
            nonlocal agent, ctx, rollback
            cmd = parse_slash_command(text, set(), _skill_names())
            if cmd.kind == "list_models":
                channel.emit(Event(type=EventType.ASSISTANT_MESSAGE, payload={
                    "text": format_models_help(ws_model[0] or _sa._runtime_cfg.get_model()),
                    "source": "system",
                }))
                return True
            if cmd.kind == "set_model":
                agent, ctx, rollback = _rebuild_stack(cmd.target)
                header_msgs[:] = list(ctx.messages)
                channel.emit(Event(type=EventType.ASSISTANT_MESSAGE, payload={
                    "text": f"已切换模型 → {cmd.target}", "source": "system",
                }))
                return True
            if cmd.kind == "list_skills":
                channel.emit(Event(type=EventType.ASSISTANT_MESSAGE, payload={
                    "text": format_skills_help(_skill_manifests()), "source": "system",
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
                        "text": result.output or "(无输出)", "source": f"skill.{cmd.target}",
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
                async with _sa._session_lock(sid):
                    ctx.coworker = (ws_mode[0] == "coworker")
                    if ctx.session_id:
                        ctx.messages = list(header_msgs)
                        from core.prompts import mode_prompt
                        from core.types import Message as _MM, Role as _Role
                        ctx.messages.append(_MM(role=_Role.SYSTEM, content=mode_prompt(ctx.coworker)))
                        ctx.bind_session(_sa._session_store, ctx.session_id, create=True)
                        pid = _sa._session_store.get_project_id(ctx.session_id)
                        ctx.mem_scope = f"web|{pid or ''}"
                        try:
                            from memory.checkpoint_store import CheckpointStore
                            _un = CheckpointStore().unfinished(ctx.session_id)
                            if _un:
                                from core.types import Message as _CM, Role as _CR
                                ctx.messages.append(_CM(role=_CR.SYSTEM, content=(
                                    "[断点续跑] 本会话上次还有未完成的待办,若与当前任务相关请接着做:\n- "
                                    + "\n- ".join(_un[:12]))))
                        except Exception:
                            pass
                        if pid:
                            block = _sa._project_store.context_block(pid)
                            if block and not any(
                                m.role == Role.SYSTEM and m.content.startswith("[工作区")
                                for m in ctx.messages
                            ):
                                from core.types import Message as _M
                                ctx.messages.insert(0, _M(role=Role.SYSTEM, content=block))
                    if await _handle_slash(text):
                        pass
                    else:
                        await coord_holder[0].run(text, ctx, channel.confirm)
                        if _sa._pref_mining_enabled():
                            asyncio.create_task(_sa._mine_preferences(list(ctx.messages)))
                            asyncio.create_task(_sa._mine_experience(list(ctx.messages)))
                            asyncio.create_task(_sa._consolidate_journal(list(ctx.messages)))
                        try:
                            from memory.pattern_tracker import PatternTracker
                            PatternTracker().record(text)
                        except Exception:
                            pass
                        try:
                            from memory.task_rating import rate_session_with_llm, record_rating
                            from config import Config
                            sid = getattr(ctx, "session_id", "") or session_id
                            llm = getattr(coord_holder[0], "llm", None) if coord_holder else None
                            score, note = await rate_session_with_llm(list(ctx.messages), llm)
                            record_rating(Config.LOG_DIR, sid, score, note)
                        except Exception:
                            pass
            except asyncio.CancelledError:
                channel.emit(Event(type=EventType.ASSISTANT_MESSAGE, payload={
                    "text": "已停止", "source": "system", "stopped": True,
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
            try:
                await ws.send_json({"type": "error",
                                    "payload": {"message": "圆桌功能已移除(单 agent 架构)"}})
            except Exception:
                pass

        async def run_debate(payload: dict) -> None:
            try:
                await ws.send_json({"type": "error",
                                    "payload": {"message": "辩论功能已移除(单 agent 架构)"}})
            except Exception:
                pass

        sender_task = asyncio.create_task(sender())
        worker_task = asyncio.create_task(worker())
        try:
            while True:
                msg = await ws.receive_json()
                if msg.get("type") == "auth":
                    continue
                if msg.get("type") == "init":
                    from llm.model_registry import normalize_model_id
                    ws_mode[0] = str(msg.get("mode", "") or "")
                    if "model" in msg:
                        ws_model[0] = normalize_model_id(str(msg.get("model")))
                    elif "provider" in msg:
                        ws_model[0] = normalize_model_id(str(msg.get("provider")))
                    new_sid = msg.get("session_id", "default")
                    task_running = (chat_task_holder[0] is not None
                                    and not chat_task_holder[0].done())
                    is_new_session = not _sa._session_store.session_exists(new_sid)
                    if task_running and is_new_session:
                        chat_task_holder[0].cancel()
                        try:
                            await chat_task_holder[0]
                        except asyncio.CancelledError:
                            pass
                        chat_task_holder[0] = None
                        task_running = False
                    if task_running:
                        await send_history_peek(new_sid)
                    else:
                        agent, ctx, rollback = _rebuild_stack(ws_model[0])
                        coordinator = coord_holder[0]
                        header_msgs = list(ctx.messages)
                        ctx.task_auto_approve = False
                        ctx.capability_grants.clear()
                        ctx.grants.clear()
                        await bind_and_send_history(new_sid)
                elif msg.get("type") == "rollback":
                    tid = msg.get("trace_id") or getattr(agent, "last_trace_id", "")
                    rb = rollback_holder[0] if rollback_holder else rollback
                    notes = rb.rollback(tid) if rb and tid else []
                    await ws.send_json({"type": "rollback_result",
                                        "payload": {"ok": bool(notes), "notes": notes}})
                elif msg.get("type") == "user":
                    channel.feed_user(msg.get("text", ""))
                elif msg.get("type") == "regenerate":
                    sid = str(msg.get("session_id") or ctx.session_id or "").strip()
                    uid = msg.get("user_msg_id")
                    if not sid:
                        continue
                    if uid is None:
                        uid = _sa._session_store.last_user_message_id(sid)
                    if not uid:
                        continue
                    row = _sa._session_store.message_at(sid, int(uid))
                    if not row or row.get("role") != "user":
                        continue
                    async with _sa._session_lock(sid):
                        _sa._session_store.truncate_after(sid, int(uid))
                        await _reload_ctx_from_db(sid)
                        await _push_history(sid)
                    channel.feed_user(row["content"])
                elif msg.get("type") == "edit_user":
                    sid = str(msg.get("session_id") or ctx.session_id or "").strip()
                    mid = msg.get("msg_id")
                    text = str(msg.get("text", "")).strip()
                    if not sid or mid is None or not text:
                        continue
                    row = _sa._session_store.message_at(sid, int(mid))
                    if not row or row.get("role") != "user":
                        continue
                    async with _sa._session_lock(sid):
                        _sa._session_store.truncate_from(sid, int(mid))
                        await _reload_ctx_from_db(sid)
                        await _push_history(sid)
                    channel.feed_user(text)
                elif msg.get("type") == "approval":
                    approved = bool(msg.get("approved"))
                    if approved and msg.get("grant_task", True):
                        ctx.task_auto_approve = True
                    cap_grant = msg.get("grant_capability")
                    if cap_grant:
                        ctx.grant_capability(str(cap_grant))
                    tg = msg.get("task_gen")
                    channel.feed_approval(approved, task_gen=int(tg) if tg is not None else None)
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
