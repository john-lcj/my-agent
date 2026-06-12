"""notify_dispatch: 统一外发通知，凭证缺失时降级为可粘贴文稿。"""
from __future__ import annotations

import os

from core.types import CapabilityResult

SCHEMA = {
    "type": "object",
    "properties": {
        "channel": {
            "type": "string",
            "description": "email | wechat | qq",
            "enum": ["email", "wechat", "qq"],
        },
        "to": {"type": "string", "description": "收件人/UserId/channel_id"},
        "subject": {"type": "string", "description": "邮件主题"},
        "body": {"type": "string", "description": "正文"},
        "group_openid": {"type": "string", "description": "QQ 群 openid"},
    },
    "required": ["channel", "to", "body"],
}


def _missing_config_hint(channel: str) -> str:
    hints = {
        "email": "EMAIL_SMTP_HOST, EMAIL_USER, EMAIL_PASS",
        "wechat": "WECHAT_CORP_ID, WECHAT_AGENT_SECRET, WECHAT_AGENT_ID",
        "qq": "QQ_BOT_APP_ID, QQ_BOT_SECRET",
    }
    return hints.get(channel, "对应渠道环境变量")


def _format_manual_draft(channel: str, to: str, subject: str, body: str) -> str:
    lines = [
        "【推送凭证未配置，以下为可手动发送的文稿】",
        f"渠道: {channel}",
        f"收件: {to}",
    ]
    if subject:
        lines.append(f"主题: {subject}")
    lines.append("---")
    lines.append(body)
    lines.append("---")
    lines.append(f"请配置: {_missing_config_hint(channel)}")
    return "\n".join(lines)


async def run(args: dict, ctx) -> CapabilityResult:
    channel = str(args.get("channel", "")).strip().lower()
    to = str(args.get("to", "")).strip()
    body = str(args.get("body", "")).strip()
    subject = str(args.get("subject", "")).strip()
    group_openid = str(args.get("group_openid", "")).strip()

    if channel not in ("email", "wechat", "qq"):
        return CapabilityResult(ok=False, error="channel 须为 email/wechat/qq")
    if not to or not body:
        return CapabilityResult(ok=False, error="缺少 to 或 body")

    from capabilities.tools.notify import SendEmail, SendQQ, SendWeChat

    try:
        if channel == "email":
            if not os.environ.get("EMAIL_SMTP_HOST") or not os.environ.get("EMAIL_USER"):
                return CapabilityResult(
                    ok=True,
                    output=_format_manual_draft(channel, to, subject, body),
                )
            result = await SendEmail().invoke(
                {"to": to, "subject": subject or "(无主题)", "body": body}, ctx
            )
        elif channel == "wechat":
            if not os.environ.get("WECHAT_CORP_ID") or not os.environ.get("WECHAT_AGENT_SECRET"):
                return CapabilityResult(
                    ok=True,
                    output=_format_manual_draft(channel, to, subject, body),
                )
            result = await SendWeChat().invoke({"to_user": to, "content": body}, ctx)
        else:
            if not os.environ.get("QQ_BOT_APP_ID"):
                return CapabilityResult(
                    ok=True,
                    output=_format_manual_draft(channel, to, subject, body),
                )
            payload = {"content": body, "channel_id": to}
            if group_openid:
                payload = {"content": body, "group_openid": group_openid}
            result = await SendQQ().invoke(payload, ctx)

        if result.ok:
            return result
        # 发送失败仍附带文稿便于人工补发
        return CapabilityResult(
            ok=True,
            output=f"{result.error or '发送失败'}\n\n{_format_manual_draft(channel, to, subject, body)}",
        )
    except Exception as e:
        return CapabilityResult(
            ok=True,
            output=f"异常: {e}\n\n{_format_manual_draft(channel, to, subject, body)}",
        )
