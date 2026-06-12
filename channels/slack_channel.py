"""Slack Events API 渠道 —— Webhook 收消息 + chat.postMessage 回复。

配置(.env 或 channels.json):
  SLACK_BOT_TOKEN       Bot User OAuth Token (xoxb-...)
  SLACK_SIGNING_SECRET  用于校验 X-Slack-Signature(测试可留空跳过)
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import time
import uuid
from typing import Any, Optional

from core.types import CapabilityCall, Decision, Event, EventType, Identity


class SlackChannel:
    name = "slack"

    def __init__(self, bot_token: str = "", signing_secret: str = "") -> None:
        self.bot_token = bot_token or os.environ.get("SLACK_BOT_TOKEN", "")
        self.signing_secret = signing_secret or os.environ.get("SLACK_SIGNING_SECRET", "")
        self._inbox: asyncio.Queue[Optional[tuple[dict, str]]] = asyncio.Queue()
        self._pending_confirm: dict[str, asyncio.Future] = {}
        self._current_ctx: dict = {}

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
            asyncio.get_event_loop().create_task(self._reply(text))
        elif event.type == EventType.ERROR:
            asyncio.get_event_loop().create_task(
                self._reply(f"⚠️ {event.payload.get('message', '')}")
            )

    async def confirm(self, call: CapabilityCall, decision: Decision, reason: str = "") -> bool:
        if not self._current_ctx:
            return False
        cid = uuid.uuid4().hex[:6].upper()
        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        self._pending_confirm[cid] = fut
        why = f"\n原因:{reason}" if reason else ""
        await self._reply(
            f"需要确认能力 [{call.name}]{why}\n"
            f"回复 `y {cid}` 允许,`n {cid}` 拒绝(60秒内)。"
        )
        try:
            return await asyncio.wait_for(fut, timeout=60.0)
        except asyncio.TimeoutError:
            return False
        finally:
            self._pending_confirm.pop(cid, None)

    def identity(self) -> Identity:
        uid = self._current_ctx.get("user", "slack-user")
        return Identity(subject_id=str(uid), agent_name="main", channel="slack")

    def feed_message(self, channel_id: str, user_id: str, text: str) -> None:
        """测试/开发:直接喂入一条消息。"""
        self._inbox.put_nowait(({"channel": channel_id, "user": user_id}, text))

    async def handle_webhook(self, body: bytes, headers: dict) -> dict:
        """处理 Slack Events 回调。返回 JSON 响应体。

        安全:未配置 signing_secret 时默认**拒绝**(fail-closed)——Slack 每个应用
        都有 signing secret,缺它即无法验签,接受未签名请求等于把入口对公网敞开。
        本地调试可设 SLACK_ALLOW_UNSIGNED=1 显式放行。
        """
        if not self.signing_secret:
            if os.environ.get("SLACK_ALLOW_UNSIGNED", "") == "1":
                pass  # 显式放行(仅供本地调试)
            else:
                return {"error": "signing secret not configured (set SLACK_SIGNING_SECRET)"}
        elif not self._verify_signature(body, headers):
            return {"error": "invalid signature"}

        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception:
            return {"error": "invalid json"}

        if payload.get("type") == "url_verification":
            return {"challenge": payload.get("challenge", "")}

        if payload.get("type") == "event_callback":
            ev = payload.get("event") or {}
            if ev.get("bot_id") or ev.get("subtype"):
                return {"ok": True}
            text = (ev.get("text") or "").strip()
            if not text:
                return {"ok": True}
            channel_id = ev.get("channel", "")
            user_id = ev.get("user", "unknown")
            handled = self._try_confirm_reply(text, user_id)
            if not handled:
                self._inbox.put_nowait(({"channel": channel_id, "user": user_id}, text))
        return {"ok": True}

    def _try_confirm_reply(self, text: str, user_id: str) -> bool:
        parts = text.strip().split()
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

    def _verify_signature(self, body: bytes, headers: dict) -> bool:
        ts = headers.get("x-slack-request-timestamp") or headers.get("X-Slack-Request-Timestamp")
        sig = headers.get("x-slack-signature") or headers.get("X-Slack-Signature")
        if not ts or not sig:
            return False
        try:
            if abs(time.time() - int(ts)) > 60 * 5:
                return False
        except ValueError:
            return False
        base = f"v0:{ts}:{body.decode('utf-8')}"
        digest = "v0=" + hmac.new(
            self.signing_secret.encode(), base.encode(), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(digest, sig)

    async def _reply(self, text: str) -> None:
        if not self.bot_token or not self._current_ctx.get("channel"):
            return
        try:
            import aiohttp
        except ImportError:
            return
        url = "https://slack.com/api/chat.postMessage"
        payload = {
            "channel": self._current_ctx["channel"],
            "text": text[:4000],
        }
        headers = {"Authorization": f"Bearer {self.bot_token}"}
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers, timeout=30) as resp:
                await resp.json()

    async def send_proactive(self, channel_id: str, text: str) -> None:
        """定时任务等主动推送。"""
        self._current_ctx = {"channel": channel_id, "user": "scheduler"}
        await self._reply(text)
