"""主动通知能力 —— 让 agent 可以主动推送消息(而不只是被动回复)。

场景举例:
  - "任务完成了发邮件给我"

能力对象:
  SendEmail   风险 WRITE —— 涉及外部数据外发,需确认

只保留邮件外发(QQ/微信等 IM 渠道已移除;日常走手机直连 Web UI)。
凭证从环境变量读取(与邮件 Channel 共用同一套配置)。
"""
from __future__ import annotations

import os
import smtplib
import ssl
import time
from email.mime.text import MIMEText
from typing import Any

from core.types import CapabilityResult, Risk


# ── 邮件发送 ──────────────────────────────────────────────────────────────────

class SendEmail:
    name = "notify.email"
    risk = Risk.WRITE
    description = "发送一封电子邮件(主动通知用途)。"
    schema = {
        "type": "object",
        "properties": {
            "to": {"type": "string", "description": "收件人地址"},
            "subject": {"type": "string", "description": "邮件主题"},
            "body": {"type": "string", "description": "邮件正文"},
        },
        "required": ["to", "subject", "body"],
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        to = str(args.get("to", "")).strip()
        subject = str(args.get("subject", "")).strip()
        body = str(args.get("body", "")).strip()
        if not to or not subject:
            return CapabilityResult(ok=False, error="缺少 to 或 subject")

        smtp_host = os.environ.get("EMAIL_SMTP_HOST", "")
        smtp_port = int(os.environ.get("EMAIL_SMTP_PORT", "465"))
        user = os.environ.get("EMAIL_USER", "")
        password = os.environ.get("EMAIL_PASS", "")
        if not smtp_host or not user:
            return CapabilityResult(ok=False, error="EMAIL_SMTP_HOST / EMAIL_USER 未配置")

        try:
            import asyncio
            await asyncio.get_event_loop().run_in_executor(
                None, _smtp_send, smtp_host, smtp_port, user, password, to, subject, body
            )
            return CapabilityResult(ok=True, output=f"邮件已发送至 {to}")
        except Exception as e:
            return CapabilityResult(ok=False, error=str(e))


def _smtp_send(host, port, user, password, to, subject, body):
    msg = MIMEText(body, "plain", "utf-8")
    msg["From"], msg["To"], msg["Subject"] = user, to, subject
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(host, port, context=ctx) as s:
        s.login(user, password)
        s.send_message(msg)


