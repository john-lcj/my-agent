"""Telegram Bot 渠道 —— Webhook 收消息 + sendMessage 回复。

配置:
  TELEGRAM_BOT_TOKEN   BotFather 颁发的 token
  TELEGRAM_WEBHOOK_SECRET  可选,URL 路径校验用
"""
from __future__ import annotations

import asyncio
import hmac
import json
import os
import uuid
from typing import Optional

from core.types import CapabilityCall, Decision, Event, EventType, Identity


class TelegramChannel:
    name = "telegram"

    def __init__(self, bot_token: str = "") -> None:
        self.bot_token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        # 注册 webhook 时设置的 secret_token;Telegram 每次回调以
        # X-Telegram-Bot-Api-Secret-Token 头回传,设置后即可验证来源真实性。
        self.webhook_secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
        self._api = f"https://api.telegram.org/bot{self.bot_token}" if self.bot_token else ""
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
            f"需要确认 [{call.name}]{why}\n回复 y {cid} 允许 / n {cid} 拒绝(60秒)。"
        )
        try:
            return await asyncio.wait_for(fut, timeout=60.0)
        except asyncio.TimeoutError:
            return False
        finally:
            self._pending_confirm.pop(cid, None)

    def identity(self) -> Identity:
        uid = self._current_ctx.get("user", "telegram-user")
        return Identity(subject_id=str(uid), agent_name="main", channel="telegram")

    def feed_update(self, update: dict) -> None:
        """测试/开发:直接喂入 Telegram update 对象。"""
        msg = update.get("message") or update.get("edited_message") or {}
        text = (msg.get("text") or "").strip()
        if not text:
            return
        chat = msg.get("chat") or {}
        user = (msg.get("from") or {}).get("id", "unknown")
        if self._try_confirm_reply(text):
            return
        self._inbox.put_nowait(({
            "chat_id": chat.get("id"),
            "user": user,
        }, text))

    async def handle_webhook(self, body: bytes, headers: dict | None = None) -> dict:
        # 若配置了 secret_token,则校验回调来源(防止他人伪造 update 灌入)。
        if self.webhook_secret:
            provided = (headers or {}).get("x-telegram-bot-api-secret-token", "")
            if not hmac.compare_digest(provided, self.webhook_secret):
                return {"error": "invalid secret token"}
        try:
            update = json.loads(body.decode("utf-8"))
        except Exception:
            return {"error": "invalid json"}
        self.feed_update(update)
        return {"ok": True}

    def _try_confirm_reply(self, text: str) -> bool:
        parts = text.strip().split()
        if len(parts) != 2:
            return False
        action, cid = parts[0].lower(), parts[1].upper()
        fut = self._pending_confirm.get(cid)
        if fut is None or fut.done():
            return False
        if action in ("y", "yes"):
            fut.set_result(True)
            return True
        if action in ("n", "no"):
            fut.set_result(False)
            return True
        return False

    async def _reply(self, text: str) -> None:
        chat_id = self._current_ctx.get("chat_id")
        if not self._api or chat_id is None:
            return
        try:
            import aiohttp
        except ImportError:
            return
        url = f"{self._api}/sendMessage"
        payload = {"chat_id": chat_id, "text": text[:4096]}
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=30) as resp:
                await resp.json()

    async def send_proactive(self, chat_id: str | int, text: str) -> None:
        self._current_ctx = {"chat_id": chat_id, "user": "scheduler"}
        await self._reply(text)
