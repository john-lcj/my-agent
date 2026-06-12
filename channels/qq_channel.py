"""QQ 机器人渠道 —— QQ 官方机器人平台(2024 新版 API)。

官方文档: https://bot.q.qq.com/wiki/
接入方式:
  - webhook 模式:QQ 平台推送 POST 到 /webhook/qq,本 channel 验签后入队。
  - 发送:调用 REST API v2 接口发消息。

支持场景:
  - QQ 频道(Guild)消息 —— 较成熟,申请门槛低
  - QQ 群/私聊消息 —— 2024 年新开放的 v2 API

学习点:
  - QQ Bot 采用 Ed25519 签名验证入站消息。
  - 不同消息场景(频道/群/私聊)发送 API 路径不同,用 msg_scene 字段区分。
  - 软边界确认:发一条确认消息,等待 "y 确认码" / "n 确认码" 回复。

配置(仅需两项,.env 或 Web 设置页):
  QQ_BOT_APP_ID        机器人 AppID
  QQ_BOT_SECRET        机器人 AppSecret
  QQ_BOT_SANDBOX       1=沙箱 0=正式(默认 0)

鉴权说明(2024+):官方已弃用 Bot {appId}.{token},需先换 AccessToken,
请求头为 Authorization: QQBot {access_token}。
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from typing import Any, Optional

from core.types import CapabilityCall, Decision, Event, EventType, Identity

_API_PROD = "https://api.sgroup.qq.com"
_API_SAND = "https://sandbox.api.sgroup.qq.com"
_TOKEN_URL = "https://bots.qq.com/app/getAppAccessToken"
_WEBHOOK_PATH = "/webhook/qq"
_MAX_REPLY_LEN = 3800

# 官方事件:群@ / 单聊 / 频道@
_INBOUND_EVENTS = frozenset({
    "GROUP_AT_MESSAGE_CREATE",
    "C2C_MESSAGE_CREATE",
    "AT_MESSAGE_CREATE",
    "DIRECT_MESSAGE_CREATE",
    "MESSAGE_CREATE",
})


class _AccessTokenCache:
    def __init__(self) -> None:
        self._token = ""
        self._expires_at = 0.0

    async def get(self, app_id: str, client_secret: str) -> str:
        if not app_id or not client_secret:
            raise ValueError("缺少 QQ_BOT_APP_ID 或 AppSecret")
        now = time.time()
        if self._token and now < self._expires_at - 60:
            return self._token
        import aiohttp
        async with aiohttp.ClientSession() as s:
            async with s.post(
                _TOKEN_URL,
                json={"appId": app_id, "clientSecret": client_secret},
                timeout=15,
            ) as resp:
                data = await resp.json()
                if resp.status != 200 or not data.get("access_token"):
                    raise RuntimeError(
                        f"获取 AccessToken 失败({resp.status}): {data}"
                    )
                self._token = data["access_token"]
                self._expires_at = now + float(data.get("expires_in", 7200))
                return self._token


class QQChannel:
    name = "qq"

    def __init__(
        self,
        app_id: str = "",
        app_secret: str = "",
        sandbox: bool = False,
        *,
        token: str = "",
        secret: str = "",
    ) -> None:
        self.app_id = app_id or os.environ.get("QQ_BOT_APP_ID", "")
        self._client_secret = (
            app_secret
            or secret
            or token
            or os.environ.get("QQ_BOT_SECRET", "")
            or os.environ.get("QQ_BOT_TOKEN", "")
        )
        use_sandbox = sandbox or (os.environ.get("QQ_BOT_SANDBOX", "0") == "1")
        self._api_base = _API_SAND if use_sandbox else _API_PROD
        self._access = _AccessTokenCache()

        self._inbox: asyncio.Queue[Optional[tuple[dict, str]]] = asyncio.Queue()
        self._pending_confirm: dict[str, asyncio.Future] = {}
        self._current_ctx: dict = {}
        self._reply_buf = ""

    # ── Channel 协议 ───────────────────────────────────────────────────────────

    async def receive(self) -> Optional[str]:
        item = await self._inbox.get()
        if item is None:
            return None
        msg_ctx, text = item
        self._current_ctx = msg_ctx
        self._reply_buf = ""
        return text

    def emit(self, event: Event) -> None:
        if not self._current_ctx:
            return
        if event.type == EventType.ASSISTANT_TOKEN:
            token = event.payload.get("token", "")
            if token:
                self._reply_buf += token
            return
        if event.type == EventType.ASSISTANT_MESSAGE:
            text = event.payload.get("text", "") or self._reply_buf
            self._reply_buf = ""
            if text:
                asyncio.get_event_loop().create_task(self._reply(text))
        elif event.type == EventType.ERROR:
            self._reply_buf = ""
            msg = event.payload.get("message", "")
            asyncio.get_event_loop().create_task(self._reply(f"⚠️ {msg}"))

    async def confirm(self, call: CapabilityCall, decision: Decision, reason: str = "") -> bool:
        if not self._current_ctx:
            return False
        confirm_id = uuid.uuid4().hex[:6].upper()
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_confirm[confirm_id] = future

        msg = (
            f"🔔 Agent 需要你确认:\n"
            f"能力: {call.name}\n"
            f"参数: {json.dumps(call.args, ensure_ascii=False)}\n"
            f"意图: {call.intent or '(未声明)'}\n"
            + (f"治理: {reason}\n" if reason else "") + "\n"
            f"回复  y {confirm_id}  确认\n"
            f"回复  n {confirm_id}  拒绝\n"
            f"⚠️ 60 秒内未回复将自动拒绝"
        )
        await self._reply(msg)
        try:
            return await asyncio.wait_for(future, timeout=60.0)
        except asyncio.TimeoutError:
            return False
        finally:
            self._pending_confirm.pop(confirm_id, None)

    def identity(self) -> Identity:
        user_id = self._current_ctx.get("author_id", "qq-user")
        return Identity(subject_id=user_id, agent_name="main", channel="qq")

    # ── Webhook 入口(由 server/app.py 调用)───────────────────────────────────

    async def handle_callback(self, body: bytes, headers: dict) -> dict:
        """处理 QQ 平台推送的事件(验签 + 解析)。"""
        payload = json.loads(body.decode("utf-8", "replace"))
        op = payload.get("op", -1)

        # op=13: URL 验证(首次配置 webhook)
        if op == 13:
            return await self._handle_url_validation(payload)

        # op=0: 分发事件
        if op == 0:
            await self._dispatch(payload)

        return {"op": 12}   # ACK

    async def _handle_url_validation(self, payload: dict) -> dict:
        """Ed25519 签名验证 + 返回 challenge(算法与官方 Go 示例一致)。"""
        event_ts = payload.get("d", {}).get("event_ts", "")
        plain_token = payload.get("d", {}).get("plain_token", "")
        bot_secret = self._client_secret
        if not bot_secret:
            print("[qq] URL 验证失败:未配置 AppSecret(设置页 Secret 或 Token 栏)")
            return {"plain_token": plain_token, "signature": ""}
        try:
            signature = _qq_callback_sign(bot_secret, event_ts, plain_token)
            return {"plain_token": plain_token, "signature": signature}
        except Exception as e:
            print(f"[qq] URL 验证签名失败: {e}")
            return {"plain_token": plain_token, "signature": ""}

    async def _dispatch(self, payload: dict) -> None:
        t = payload.get("t", "")
        if t and t not in _INBOUND_EVENTS:
            return

        d = payload.get("d", {})
        parsed = _parse_inbound_event(t, d)
        if not parsed:
            return
        text, msg_ctx = parsed

        import re
        m = re.match(r"^([yYnN])\s+([A-F0-9]{6})$", text)
        if m:
            approved = m.group(1).upper() == "Y"
            cid = m.group(2)
            fut = self._pending_confirm.get(cid)
            if fut and not fut.done():
                fut.set_result(approved)
            return

        self._inbox.put_nowait((msg_ctx, text))

    async def test_connection(self) -> dict:
        """测试 AppID + AppSecret 能否换取 AccessToken。"""
        try:
            token = await self._access.get(self.app_id, self._client_secret)
            return {"ok": True, "detail": f"AccessToken 获取成功(前缀 {token[:8]}…)"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def send_proactive(self, deliver_to: str, subject: str, body: str) -> None:
        """定时任务等场景主动推送。deliver_to 格式:
        group:<openid> | user:<openid> | channel:<channel_id>
        """
        if not deliver_to or not self.app_id or not self._client_secret:
            raise ValueError("QQ 投递需要 deliver_to 及 AppID/AppSecret")
        text = f"{subject}\n\n{body}" if subject else body
        ctx: dict[str, Any] = {"msg_id": ""}
        if deliver_to.startswith("group:"):
            ctx["group_openid"] = deliver_to.split(":", 1)[1]
        elif deliver_to.startswith("user:"):
            ctx["openid"] = deliver_to.split(":", 1)[1]
        elif deliver_to.startswith("channel:"):
            ctx["channel_id"] = deliver_to.split(":", 1)[1]
        else:
            # 兼容:直接填 openid 时按群消息尝试
            ctx["group_openid"] = deliver_to
        saved = self._current_ctx
        self._current_ctx = ctx
        try:
            await self._reply(text)
        finally:
            self._current_ctx = saved

    async def _reply(self, content: str) -> None:
        ctx = self._current_ctx
        if not ctx:
            return
        if len(content) > _MAX_REPLY_LEN:
            content = content[: _MAX_REPLY_LEN - 16] + "\n…(消息过长已截断)"
        if not self.app_id or not self._client_secret:
            print("[qq] 发送失败:缺少 AppID 或 AppSecret")
            return

        try:
            access = await self._access.get(self.app_id, self._client_secret)
        except Exception as e:
            print(f"[qq] AccessToken 获取失败: {e}")
            return

        headers = {
            "Authorization": f"QQBot {access}",
            "Content-Type": "application/json",
        }

        try:
            import aiohttp
            async with aiohttp.ClientSession() as s:
                if ctx.get("group_openid"):
                    # QQ 群消息(v2)
                    url = f"{self._api_base}/v2/groups/{ctx['group_openid']}/messages"
                    body: dict[str, Any] = {
                        "content": content,
                        "msg_type": 0,
                        "msg_id": ctx.get("msg_id", ""),
                    }
                elif ctx.get("openid"):
                    # QQ 私聊(v2)
                    url = f"{self._api_base}/v2/users/{ctx['openid']}/messages"
                    body = {
                        "content": content,
                        "msg_type": 0,
                        "msg_id": ctx.get("msg_id", ""),
                    }
                elif ctx.get("channel_id"):
                    # 频道消息
                    url = f"{self._api_base}/channels/{ctx['channel_id']}/messages"
                    body = {
                        "content": content,
                        "msg_id": ctx.get("msg_id", ""),
                    }
                else:
                    print(f"[qq] 未知消息场景 type={ctx.get('type')!r}, ctx={ctx}")
                    return
                async with s.post(url, headers=headers, json=body) as resp:
                    if resp.status >= 400:
                        detail = await resp.text()
                        print(f"[qq] 发送失败 HTTP {resp.status}: {detail[:300]}")
        except Exception as e:
            print(f"[qq] 发送失败: {e}")


def _parse_inbound_event(event_type: str, d: dict) -> Optional[tuple[str, dict]]:
    """解析群@ / 单聊 / 频道@ 入站消息。"""
    text = (
        d.get("content")
        or (d.get("msg") or {}).get("content")
        or ""
    ).strip()
    if text.startswith("<@") and ">" in text:
        text = text[text.index(">") + 1:].strip()
    if not text:
        return None

    author = d.get("author") or {}
    author_id = (
        author.get("id")
        or author.get("user_openid")
        or author.get("member_openid")
        or d.get("author_id")
        or "qq-user"
    )

    msg_ctx = {
        "type": event_type,
        "author_id": str(author_id),
        "channel_id": d.get("channel_id"),
        "guild_id": d.get("guild_id"),
        "group_openid": d.get("group_openid"),
        "openid": d.get("openid") or author.get("user_openid"),
        "msg_id": d.get("id") or (d.get("msg") or {}).get("id", ""),
    }
    return text, msg_ctx


def qq_channel_info(*, public_base_url: str = "") -> dict:
    """返回 QQ 渠道配置与 webhook 信息(供启动器 / API 使用)。"""
    app_id = os.environ.get("QQ_BOT_APP_ID", "")
    has_secret = bool(os.environ.get("QQ_BOT_SECRET") or os.environ.get("QQ_BOT_TOKEN"))
    sandbox = os.environ.get("QQ_BOT_SANDBOX", "0") == "1"
    base = (public_base_url or os.environ.get("AGENT_PUBLIC_URL", "")).rstrip("/")
    webhook = f"{base}{_WEBHOOK_PATH}" if base else _WEBHOOK_PATH
    return {
        "channel": "qq",
        "configured": bool(app_id and has_secret),
        "app_id": app_id,
        "sandbox": sandbox,
        "webhook_path": _WEBHOOK_PATH,
        "webhook_url": webhook,
        "api_base": _API_SAND if sandbox else _API_PROD,
        "docs": "https://bot.q.qq.com/wiki/",
    }


def print_qq_status() -> None:
    """CLI 打印 QQ 机器人状态。"""
    info = qq_channel_info()
    print("QQ 机器人(内置 qqbot)")
    print(f"  配置: {'已填写 AppID+Secret' if info['configured'] else '未完成'}")
    if info["app_id"]:
        print(f"  AppID: {info['app_id']}")
    print(f"  环境: {'沙箱' if info['sandbox'] else '正式'}")
    print(f"  Webhook 路径: {info['webhook_path']}")
    print(f"  回调 URL: {info['webhook_url']}")
    print("  在 QQ 开放平台 → 开发设置 → 回调地址 填入公网 HTTPS 地址")
    print("  配置: 仅需 AppID + AppSecret(Web 设置页或 .env)")


def _qq_callback_sign(bot_secret: str, event_ts: str, plain_token: str) -> str:
    """QQ 开放平台回调地址验证签名(见官方文档 event-emit)。"""
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ImportError as e:
        raise RuntimeError("需要 cryptography: pip install cryptography") from e

    seed_size = 32
    seed = bot_secret
    while len(seed) < seed_size:
        seed = seed + seed
    seed_bytes = seed[:seed_size].encode("utf-8")
    private_key = Ed25519PrivateKey.from_private_bytes(seed_bytes)
    msg = f"{event_ts}{plain_token}".encode("utf-8")
    return private_key.sign(msg).hex()
