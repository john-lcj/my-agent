"""notify_dispatch: 统一外发通知，凭证缺失时降级为可粘贴文稿。"""
from __future__ import annotations

import os

from core.types import CapabilityResult

SCHEMA = {
    "type": "object",
    "properties": {
        "channel": {
            "type": "string",
            "description": "email(目前仅支持邮件)",
            "enum": ["email"],
        },
        "to": {"type": "string", "description": "收件人邮箱"},
        "subject": {"type": "string", "description": "邮件主题"},
        "body": {"type": "string", "description": "正文"},
    },
    "required": ["channel", "to", "body"],
}


def _missing_config_hint(channel: str) -> str:
    hints = {
        "email": "EMAIL_SMTP_HOST, EMAIL_USER, EMAIL_PASS",
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

    if channel not in ("email",):
        return CapabilityResult(ok=False, error="channel 仅支持 email(其余 IM 渠道已移除)")
    if not to or not body:
        return CapabilityResult(ok=False, error="缺少 to 或 body")

    from capabilities.tools.notify import SendEmail

    try:
        if not os.environ.get("EMAIL_SMTP_HOST") or not os.environ.get("EMAIL_USER"):
            return CapabilityResult(
                ok=True,
                output=_format_manual_draft(channel, to, subject, body),
            )
        result = await SendEmail().invoke(
            {"to": to, "subject": subject or "(无主题)", "body": body}, ctx
        )

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
