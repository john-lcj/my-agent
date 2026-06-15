"""邮件渠道 —— IMAP 轮询收信 + SMTP 发信。

支持 QQ 邮箱、163、Gmail、企业邮箱等任意标准 IMAP/SMTP 服务。

工作模式:
  1. start_polling()  在后台持续轮询 INBOX,把新邮件喂进 _inbox 队列。
  2. receive()        从队列取出下一封邮件(阻塞等待)。
  3. emit()           把 agent 的 AssistantMessage/Error 事件回复给发件人。
  4. confirm()        遇到软边界时,给发件人发一封确认邮件,等待 60 秒内回复 y/n,
                      超时默认拒绝(fail-safe)。

配置(通过 .env):
  EMAIL_IMAP_HOST / EMAIL_IMAP_PORT  默认 993(SSL)
  EMAIL_SMTP_HOST / EMAIL_SMTP_PORT  默认 465(SSL)
  EMAIL_USER     发件人/登录账号
  EMAIL_PASS     授权码(QQ/163 用授权码,不是登录密码)
  EMAIL_POLL_SEC 轮询间隔,默认 30 秒
"""
from __future__ import annotations

import asyncio
import email as _email_lib
import imaplib
import os
import re
import smtplib
import ssl
import time
import uuid
from email.mime.text import MIMEText
from typing import Optional

from core.types import CapabilityCall, Decision, Event, EventType, Identity


class EmailChannel:
    name = "email"

    def __init__(
        self,
        imap_host: str = "",
        imap_port: int = 993,
        smtp_host: str = "",
        smtp_port: int = 465,
        user: str = "",
        password: str = "",
        poll_sec: float = 30.0,
    ) -> None:
        self.imap_host = imap_host or os.environ.get("EMAIL_IMAP_HOST", "")
        self.imap_port = imap_port or int(os.environ.get("EMAIL_IMAP_PORT", "993"))
        self.smtp_host = smtp_host or os.environ.get("EMAIL_SMTP_HOST", "")
        self.smtp_port = smtp_port or int(os.environ.get("EMAIL_SMTP_PORT", "465"))
        self.user = user or os.environ.get("EMAIL_USER", "")
        self.password = password or os.environ.get("EMAIL_PASS", "")
        self.poll_sec = poll_sec or float(os.environ.get("EMAIL_POLL_SEC", "30"))
        # 白名单:只响应这些发件人的邮件(逗号分隔)。默认只听自己,防陌生人驱使 agent。
        raw_allow = os.environ.get("EMAIL_ALLOWED_SENDERS", "").strip()
        self.allowed = {a.strip().lower() for a in raw_allow.split(",") if a.strip()} or (
            {self.user.lower()} if self.user else set())

        self._inbox: asyncio.Queue[Optional[tuple[str, str]]] = asyncio.Queue()
        self._pending_confirm: dict[str, asyncio.Future] = {}
        self._current_sender: str = ""
        self._loop: Optional[asyncio.AbstractEventLoop] = None  # 主线程事件循环句柄(供轮询子线程跨线程投递)

    # ── Channel 协议 ───────────────────────────────────────────────────────────

    async def receive(self) -> Optional[str]:
        """等待下一封入站邮件,返回邮件正文。"""
        item = await self._inbox.get()
        if item is None:
            return None
        sender, body = item
        self._current_sender = sender
        return body

    def emit(self, event: Event) -> None:
        if not self._current_sender:
            return
        if event.type == EventType.ASSISTANT_MESSAGE:
            text = event.payload.get("text", "")
            asyncio.get_event_loop().create_task(
                self._send_email(self._current_sender, "Re: Agent 回复", text)
            )
        elif event.type == EventType.ERROR:
            msg = event.payload.get("message", "")
            asyncio.get_event_loop().create_task(
                self._send_email(self._current_sender, "Agent 错误", msg)
            )

    async def confirm(self, call: CapabilityCall, decision: Decision, reason: str = "") -> bool:
        """向邮件发件人发确认请求,等待 60 秒内回复。超时拒绝(fail-safe)。"""
        if not self._current_sender:
            return False
        confirm_id = uuid.uuid4().hex[:6].upper()
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_confirm[confirm_id] = future

        body = (
            f"Agent 需要执行以下操作,请确认:\n\n"
            f"  能力: {call.name}\n"
            f"  参数: {call.args}\n"
            f"  意图: {call.intent or '(未声明)'}\n"
            + (f"  治理: {reason}\n" if reason else "") + "\n"
            f"  回复 'Y {confirm_id}' 确认\n"
            f"  回复 'N {confirm_id}' 拒绝\n\n"
            f"  ⚠️ 60 秒内未回复将自动拒绝。"
        )
        await self._send_email(
            self._current_sender,
            f"[Agent 确认请求 {confirm_id}]",
            body,
        )
        try:
            return await asyncio.wait_for(future, timeout=60.0)
        except asyncio.TimeoutError:
            return False
        finally:
            self._pending_confirm.pop(confirm_id, None)

    def identity(self) -> Identity:
        return Identity(
            subject_id=self._current_sender or self.user,
            agent_name="main",
            channel="email",
        )

    # ── 后台轮询 ───────────────────────────────────────────────────────────────

    async def start_polling(self) -> None:
        """启动后台 IMAP 轮询任务(在 server 启动时调用)。"""
        self._loop = asyncio.get_running_loop()  # 存主线程循环,供子线程 call_soon_threadsafe
        self._loop.create_task(self._poll_loop())

    async def _poll_loop(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            try:
                await loop.run_in_executor(None, self._fetch_new)
            except Exception as e:
                print(f"[email] 轮询异常: {e}")
            await asyncio.sleep(self.poll_sec)

    def _fetch_new(self) -> None:
        """同步 IMAP 拉取 UNSEEN 邮件(在 executor 线程里运行)。"""
        ctx = ssl.create_default_context()
        with imaplib.IMAP4_SSL(self.imap_host, self.imap_port, ssl_context=ctx) as imap:
            imap.login(self.user, self.password)
            imap.select("INBOX")
            _, msg_ids = imap.search(None, "UNSEEN")
            for mid in (msg_ids[0].split() if msg_ids[0] else []):
                _, data = imap.fetch(mid, "(RFC822)")
                raw = data[0][1] if data and data[0] else b""
                msg = _email_lib.message_from_bytes(raw)

                sender = _parse_addr(msg.get("From", ""))
                subject = _decode_header(msg.get("Subject", ""))
                body = _extract_body(msg)

                # 白名单过滤:非许可发件人直接忽略(防陌生人驱使 agent / 烧额度)
                if self.allowed and sender.strip().lower() not in self.allowed:
                    print(f"[email] 忽略非白名单发件人: {sender}")
                    continue

                # 处理确认回复(格式: "Y ABC123" 或 "N ABC123")
                confirm_match = re.search(r"^([YNyn])\s+([A-F0-9]{6})", body.strip())
                if confirm_match:
                    answer = confirm_match.group(1).upper() == "Y"
                    cid = confirm_match.group(2).upper()
                    fut = self._pending_confirm.get(cid)
                    if fut and not fut.done() and self._loop is not None:
                        self._loop.call_soon_threadsafe(fut.set_result, answer)
                    continue

                # 普通消息
                if self._loop is not None:
                    self._loop.call_soon_threadsafe(
                        self._inbox.put_nowait, (sender, f"[邮件主题:{subject}]\n{body}")
                    )
            imap.logout()

    async def _send_email(self, to: str, subject: str, body: str) -> None:
        await asyncio.get_event_loop().run_in_executor(
            None, self._send_sync, to, subject, body
        )

    def _send_sync(self, to: str, subject: str, body: str) -> None:
        msg = MIMEText(body, "plain", "utf-8")
        msg["From"] = self.user
        msg["To"] = to
        msg["Subject"] = subject
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, context=ctx) as smtp:
            smtp.login(self.user, self.password)
            smtp.send_message(msg)

    def test_connection(self) -> dict:
        """同步验证 IMAP + SMTP 登录,返回 {ok, imap, smtp, error}。供"连通测试"用。"""
        result = {"ok": False, "imap": False, "smtp": False, "error": ""}
        if not (self.user and self.password):
            result["error"] = "缺少账号或授权码"
            return result
        ctx = ssl.create_default_context()
        try:
            with imaplib.IMAP4_SSL(self.imap_host, self.imap_port, ssl_context=ctx) as imap:
                imap.login(self.user, self.password)
                imap.select("INBOX")
                imap.logout()
            result["imap"] = True
        except Exception as e:
            result["error"] = f"IMAP 失败: {e}"
            return result
        try:
            with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, context=ctx) as smtp:
                smtp.login(self.user, self.password)
            result["smtp"] = True
        except Exception as e:
            result["error"] = f"SMTP 失败: {e}"
            return result
        result["ok"] = True
        return result


# ── 辅助解析 ──────────────────────────────────────────────────────────────────

def _parse_addr(raw: str) -> str:
    m = re.search(r"<([^>]+)>", raw)
    return m.group(1) if m else raw.strip()


def _decode_header(raw: str) -> str:
    import email.header
    parts = []
    for bstr, enc in email.header.decode_header(raw):
        if isinstance(bstr, bytes):
            parts.append(bstr.decode(enc or "utf-8", "replace"))
        else:
            parts.append(bstr)
    return "".join(parts)


def _extract_body(msg) -> str:
    """递归提取纯文本正文,优先 text/plain。"""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                charset = part.get_content_charset() or "utf-8"
                return part.get_payload(decode=True).decode(charset, "replace")
    else:
        charset = msg.get_content_charset() or "utf-8"
        return msg.get_payload(decode=True).decode(charset, "replace")
    return ""
