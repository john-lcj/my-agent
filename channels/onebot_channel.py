"""QQ 渠道(OneBot v11 / NapCat)—— 个人号扫码即连,最省心的接法。

为什么用 OneBot + NapCat,而不是 QQ 官方机器人:
  官方机器人要去 q.qq.com 申请、审核、配 webhook,且个人用不了群私聊全场景。
  NapCat 基于新版 QQ 内核,**终端弹二维码、手机 QQ 一扫就登录**,之后缓存免扫——
  这正是 LangBot / AstrBot / Hermes 等都在用的路子。本渠道做 OneBot v11 的"正向
  WebSocket 客户端":主动连上 NapCat 暴露的 ws,收事件、发消息,全程不需要公网回调。

连接(你只需三步,详见 CONNECT_QQ.md):
  1. 跑 scripts/napcat-up.sh 起 NapCat(docker),它会开好 OneBot WS。
  2. 浏览器/终端扫码登录你的 QQ。
  3. 启用本渠道(设 ONEBOT_WS_URL 即可),agent 自动连上、能对话。

配置(.env 或 Web 设置页,全部可选,带默认值):
  ONEBOT_WS_URL        NapCat 的正向 WS 地址,默认 ws://127.0.0.1:3001
  ONEBOT_ACCESS_TOKEN  与 NapCat 配置一致的鉴权 token(没配就留空)
  QQ_MASTER_UIN        只听这个 QQ 号的指令(强烈建议设成你自己的号,防别人在群里驱使你的 agent)

安全:对外是你的真实 QQ,务必设 QQ_MASTER_UIN;群消息默认只在 @机器人 时才响应,避免刷屏。
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from typing import Optional

from core.types import CapabilityCall, Decision, Event, EventType, Identity

_CQ_RE = re.compile(r"\[CQ:[^\]]*\]")
_AT_SELF_RE = re.compile(r"\[CQ:at,qq=(\d+)\]")


class OneBotChannel:
    name = "onebot"

    def __init__(self, ws_url: str = "", access_token: str = "", master_uin: str = "") -> None:
        self.ws_url = ws_url or os.environ.get("ONEBOT_WS_URL", "ws://127.0.0.1:3001")
        self.access_token = access_token or os.environ.get("ONEBOT_ACCESS_TOKEN", "")
        self.master_uin = str(master_uin or os.environ.get("QQ_MASTER_UIN", "")).strip()

        self._inbox: asyncio.Queue[Optional[tuple[dict, str]]] = asyncio.Queue()
        self._pending_confirm: dict[str, asyncio.Future] = {}
        self._current_ctx: dict = {}
        self._self_id: str = ""
        self._ws = None  # 运行期由 connect() 赋值
        self._closed = False

    # ── Channel 协议 ───────────────────────────────────────────────────────────

    async def receive(self) -> Optional[str]:
        item = await self._inbox.get()
        if item is None:
            return None
        self._current_ctx, text = item
        return text

    def emit(self, event: Event) -> None:
        if not self._current_ctx:
            return
        if event.type == EventType.ASSISTANT_MESSAGE:
            text = event.payload.get("text", "")
            if text:
                asyncio.get_event_loop().create_task(self._reply(self._current_ctx, text))
        elif event.type == EventType.ERROR:
            asyncio.get_event_loop().create_task(
                self._reply(self._current_ctx, f"⚠️ {event.payload.get('message', '')}")
            )

    async def confirm(self, call: CapabilityCall, decision: Decision, reason: str = "") -> bool:
        if not self._current_ctx:
            return False
        cid = uuid.uuid4().hex[:6].upper()
        fut = asyncio.get_event_loop().create_future()
        self._pending_confirm[cid] = fut
        why = f"\n原因:{reason}" if reason else ""
        await self._reply(
            self._current_ctx,
            f"需要确认 [{call.name}]{why}\n回复  y {cid}  允许 /  n {cid}  拒绝(60 秒内有效)",
        )
        try:
            return await asyncio.wait_for(fut, timeout=60.0)
        except asyncio.TimeoutError:
            return False
        finally:
            self._pending_confirm.pop(cid, None)

    def identity(self) -> Identity:
        uid = self._current_ctx.get("user_id", "qq-user")
        return Identity(subject_id=str(uid), agent_name="main", channel="qq")

    # ── 事件处理(可单测:不依赖真实 ws)──────────────────────────────────────

    def _handle_event(self, data: dict) -> None:
        """处理一条 OneBot 事件。消息→入队;心跳/响应→忽略或解析。"""
        if data.get("self_id"):
            self._self_id = str(data["self_id"])
        post_type = data.get("post_type")
        if post_type != "message":
            return  # meta_event 心跳、notice、request 等一律忽略
        msg_type = data.get("message_type")  # private / group
        user_id = str(data.get("user_id", ""))
        group_id = data.get("group_id")
        raw = str(data.get("raw_message") or data.get("message") or "")

        # 1) 优先当作"确认回复"消化(y/n 确认码),不进主对话
        clean_for_confirm = _CQ_RE.sub("", raw).strip()
        if self._try_confirm_reply(clean_for_confirm):
            return

        # 2) 主人过滤:设了 QQ_MASTER_UIN 就只听主人
        if self.master_uin and user_id != self.master_uin:
            return

        # 3) 群消息默认只在 @机器人 时响应,避免刷屏
        if msg_type == "group":
            at_ids = _AT_SELF_RE.findall(raw)
            if self._self_id and self._self_id not in at_ids:
                return

        text = _CQ_RE.sub("", raw).strip()
        if not text:
            return
        ctx = {"message_type": msg_type, "user_id": user_id, "group_id": group_id}
        self._inbox.put_nowait((ctx, text))

    def _try_confirm_reply(self, text: str) -> bool:
        parts = text.split()
        if len(parts) != 2:
            return False
        action, cid = parts[0].lower(), parts[1].upper()
        fut = self._pending_confirm.get(cid)
        if fut is None or fut.done():
            return False
        if action in ("y", "yes", "是"):
            fut.set_result(True)
            return True
        if action in ("n", "no", "否"):
            fut.set_result(False)
            return True
        return False

    def _build_send_action(self, ctx: dict, text: str) -> dict:
        """根据来源构造 OneBot send_msg 动作(私聊/群聊路由)。"""
        params: dict = {"message": text[:4500]}
        if ctx.get("message_type") == "group" and ctx.get("group_id") is not None:
            params["message_type"] = "group"
            params["group_id"] = ctx["group_id"]
        else:
            params["message_type"] = "private"
            params["user_id"] = ctx.get("user_id")
        return {"action": "send_msg", "params": params, "echo": uuid.uuid4().hex[:8]}

    # ── WebSocket 生命周期(运行时使用;测试用 _handle_event/_build_send_action)──

    async def _reply(self, ctx: dict, text: str) -> None:
        await self._send_action(self._build_send_action(ctx, text))

    async def _send_action(self, action: dict) -> None:
        ws = self._ws
        if ws is None:
            return
        try:
            await ws.send_str(json.dumps(action, ensure_ascii=False))
        except Exception as e:
            print(f"[qq/onebot] 发送失败: {e}")

    async def connect(self) -> None:
        """连上 NapCat 的正向 WS,断线自动重连。由 server 在后台 task 里调用。"""
        try:
            import aiohttp
        except ImportError:
            print("[qq/onebot] 缺少 aiohttp,无法连接")
            return
        headers = {"Authorization": f"Bearer {self.access_token}"} if self.access_token else {}
        backoff = 2
        while not self._closed:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(self.ws_url, headers=headers, heartbeat=30) as ws:
                        self._ws = ws
                        backoff = 2
                        print(f"[qq/onebot] 已连上 NapCat:{self.ws_url}")
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                try:
                                    self._handle_event(json.loads(msg.data))
                                except Exception as e:
                                    print(f"[qq/onebot] 事件处理异常: {e}")
                            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                                break
            except Exception as e:
                print(f"[qq/onebot] 连接断开,{backoff}s 后重连: {e}")
            finally:
                self._ws = None
            if self._closed:
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)

    async def close(self) -> None:
        self._closed = True
        self._inbox.put_nowait(None)


def onebot_channel_info() -> dict:
    return {
        "ws_url": os.environ.get("ONEBOT_WS_URL", "ws://127.0.0.1:3001"),
        "master_uin": os.environ.get("QQ_MASTER_UIN", "(未设·谁都能驱使,建议设成你的号)"),
        "token_set": bool(os.environ.get("ONEBOT_ACCESS_TOKEN")),
    }
