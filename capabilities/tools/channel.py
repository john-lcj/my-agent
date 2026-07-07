"""Email channel settings for agent-managed inbound and outbound allowlists.

channel.status     Show the current account and allowlists without revealing passwords.
channel.configure  Update allowlists and related email settings.
"""
from __future__ import annotations

from typing import Any

from capabilities.tools.base import Tool
from core.types import CapabilityResult, Risk

_STORE = None


def _store():
    global _STORE
    if _STORE is None:
        from config import Config
        from channels.config_store import ChannelConfigStore
        _STORE = ChannelConfigStore(path=f"{Config.LOG_DIR}/channels.json")
    return _STORE


class ChannelStatus(Tool):
    name = "channel.status"
    risk = Risk.READ
    description = (
        "Inspect email channel settings: account, inbound/outbound allowlists, "
        "and IMAP/SMTP configuration. Passwords are never returned."
    )
    schema = {"type": "object", "properties": {}}

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        import os
        st = _store()
        masked = st.get_masked().get("email", {})
        allowed = masked.get("allowed", "") or os.environ.get("EMAIL_ALLOWED_SENDERS", "")
        recipients = os.environ.get("EMAIL_ALLOWED_RECIPIENTS", "")
        user = masked.get("user", "") or os.environ.get("EMAIL_USER", "")
        lines = [
            f"账号: {user or '(未配置)'}",
            f"白名单(入站发件人): {allowed or '(未设,仅响应自己)'}",
            f"外发收件人: {recipients or '(未设,仅可发给自己)'}",
            f"IMAP: {masked.get('imap') or '(未填)'}",
            f"SMTP: {masked.get('smtp') or '(未填)'}",
            f"密码: {'已配置' if masked.get('password') else '未配置'}",
        ]
        return CapabilityResult(ok=True, output="\n".join(lines))


class ChannelConfigure(Tool):
    name = "channel.configure"
    risk = Risk.WRITE
    description = (
        "Update email channel settings. The allowed value is a comma-separated list "
        "that is applied to both inbound senders and outbound recipients."
    )
    schema = {
        "type": "object",
        "properties": {
            "allowed": {
                "type": "string",
                "description": "Comma-separated email allowlist for inbound and outbound mail",
            },
            "user": {"type": "string", "description": "Email account; optional"},
            "password": {"type": "string", "description": "App password; leave empty to keep unchanged"},
        },
        "required": ["allowed"],
    }

    async def invoke(self, args: dict, ctx: Any) -> CapabilityResult:
        import os
        allowed = str(args.get("allowed", "")).strip().replace("，", ",")
        if not allowed:
            return CapabilityResult(ok=False, error="allowed 不能为空")
        values: dict = {"allowed": allowed}
        if args.get("user"):
            values["user"] = str(args["user"]).strip()
        if args.get("password"):
            values["password"] = str(args["password"])
        st = _store()
        st.update("email", values)
        senders = os.environ.get("EMAIL_ALLOWED_SENDERS", "")
        recipients = os.environ.get("EMAIL_ALLOWED_RECIPIENTS", "")
        return CapabilityResult(
            ok=True,
            output=(
                f"已更新邮件白名单。\n"
                f"入站发件人: {senders}\n"
                f"外发收件人: {recipients}"
            ),
        )
