"""主动通知能力 —— 让 agent 可以主动推送消息(而不只是被动回复)。

场景举例:
  - "任务完成了发邮件给我"
  - "提醒小明明天开会(发企业微信)"
  - "把分析结果发到 QQ 群"

三个能力对象:
  SendEmail   风险 WRITE —— 涉及外部数据外发,需确认
  SendWeChat  风险 WRITE
  SendQQ      风险 WRITE

架构:每个能力从环境变量读取凭证(与 Channel 共用同一套配置),
这样"被动接收通道"和"主动发送能力"可以独立使用,也可以同时启用。
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


# ── 企业微信发送 ──────────────────────────────────────────────────────────────

class SendWeChat:
    name = "notify.wechat"
    risk = Risk.WRITE
    description = "通过企业微信向指定成员发送文本消息。"
    schema = {
        "type": "object",
        "properties": {
            "to_user": {"type": "string", "description": "收件人 UserId(企业微信账号)"},
            "content": {"type": "string", "description": "消息内容"},
        },
        "required": ["to_user", "content"],
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        to_user = str(args.get("to_user", "")).strip()
        content = str(args.get("content", "")).strip()
        if not to_user or not content:
            return CapabilityResult(ok=False, error="缺少 to_user 或 content")

        corp_id = os.environ.get("WECHAT_CORP_ID", "")
        secret = os.environ.get("WECHAT_SECRET", "")
        agent_id = os.environ.get("WECHAT_AGENT_ID", "")
        if not corp_id or not secret:
            return CapabilityResult(ok=False, error="WECHAT_CORP_ID / WECHAT_SECRET 未配置")

        try:
            import aiohttp
            token = await _wechat_token(corp_id, secret)
            url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"
            payload = {
                "touser": to_user,
                "msgtype": "text",
                "agentid": int(agent_id) if agent_id else 0,
                "text": {"content": content},
            }
            async with aiohttp.ClientSession() as s:
                async with s.post(url, json=payload) as r:
                    data = await r.json(content_type=None)
            if data.get("errcode", 0) != 0:
                return CapabilityResult(ok=False, error=str(data))
            return CapabilityResult(ok=True, output=f"企业微信已发送给 {to_user}")
        except Exception as e:
            return CapabilityResult(ok=False, error=str(e))


_wechat_token_cache: dict[str, tuple[str, float]] = {}


async def _wechat_token(corp_id: str, secret: str) -> str:
    cached = _wechat_token_cache.get(corp_id)
    if cached and time.time() < cached[1]:
        return cached[0]
    import aiohttp
    url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={corp_id}&corpsecret={secret}"
    async with aiohttp.ClientSession() as s:
        async with s.get(url) as r:
            data = await r.json(content_type=None)
    t = data.get("access_token", "")
    exp = time.time() + data.get("expires_in", 7200) - 60
    _wechat_token_cache[corp_id] = (t, exp)
    return t


# ── QQ 机器人发送 ─────────────────────────────────────────────────────────────

class SendQQ:
    name = "notify.qq"
    risk = Risk.WRITE
    description = "通过 QQ 机器人向频道/群发送文本消息。"
    schema = {
        "type": "object",
        "properties": {
            "channel_id": {"type": "string", "description": "QQ 频道子频道 ID"},
            "group_openid": {"type": "string", "description": "QQ 群 openid(与 channel_id 二选一)"},
            "content": {"type": "string", "description": "消息内容"},
        },
        "required": ["content"],
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        content = str(args.get("content", "")).strip()
        channel_id = str(args.get("channel_id", "")).strip()
        group_openid = str(args.get("group_openid", "")).strip()
        if not content:
            return CapabilityResult(ok=False, error="缺少 content")

        app_id = os.environ.get("QQ_BOT_APP_ID", "")
        app_secret = os.environ.get("QQ_BOT_SECRET", "") or os.environ.get("QQ_BOT_TOKEN", "")
        sandbox = os.environ.get("QQ_BOT_SANDBOX", "0") == "1"
        api = "https://sandbox.api.sgroup.qq.com" if sandbox else "https://api.sgroup.qq.com"
        if not app_id or not app_secret:
            return CapabilityResult(ok=False, error="QQ_BOT_APP_ID / QQ_BOT_SECRET 未配置")

        try:
            from channels.qq_channel import _AccessTokenCache
            access = await _AccessTokenCache().get(app_id, app_secret)
            headers = {
                "Authorization": f"QQBot {access}",
                "Content-Type": "application/json",
            }
            import aiohttp
            async with aiohttp.ClientSession() as s:
                if group_openid:
                    url = f"{api}/v2/groups/{group_openid}/messages"
                    body = {"content": content, "msg_type": 0}
                elif channel_id:
                    url = f"{api}/channels/{channel_id}/messages"
                    body = {"content": content}
                else:
                    return CapabilityResult(ok=False, error="需要提供 channel_id 或 group_openid")
                async with s.post(url, headers=headers, json=body) as r:
                    data = await r.json(content_type=None)
            if "id" not in data and data.get("code"):
                return CapabilityResult(ok=False, error=str(data))
            return CapabilityResult(ok=True, output=f"QQ 消息已发送")
        except Exception as e:
            return CapabilityResult(ok=False, error=str(e))
