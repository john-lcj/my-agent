"""企业微信回调 Webhook —— GET 验证 URL + POST 收消息。"""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import PlainTextResponse, Response

from channels.wecom_channel import WeComChannel
from channels.wecom_crypto import WeComCrypto


def register_wecom_webhook(app, ext_channels, channel_cfg) -> None:
    @app.get("/webhook/wecom")
    async def wecom_verify(
        request: Request,
        msg_signature: str = "",
        timestamp: str = "",
        nonce: str = "",
        echostr: str = "",
    ) -> PlainTextResponse:
        channel_cfg.apply_to_env()
        ch = _active_wecom(ext_channels)
        if ch is None:
            return PlainTextResponse("wecom not configured", status_code=503)
        crypto = WeComCrypto(ch.token, ch.aes_key, ch.corp_id)
        try:
            plain = crypto.verify_url(msg_signature, timestamp, nonce, echostr)
        except Exception as e:
            print(f"[wecom] URL 验证失败: {e}")
            return PlainTextResponse("verify failed", status_code=403)
        return PlainTextResponse(plain)

    @app.post("/webhook/wecom")
    async def wecom_message(
        request: Request,
        msg_signature: str = "",
        timestamp: str = "",
        nonce: str = "",
    ) -> Response:
        channel_cfg.apply_to_env()
        ch = _active_wecom(ext_channels)
        if ch is None:
            return PlainTextResponse("wecom not configured", status_code=503)
        body = await request.body()
        crypto = WeComCrypto(ch.token, ch.aes_key, ch.corp_id)
        try:
            plain_xml = crypto.decrypt_post(msg_signature, timestamp, nonce, body)
        except Exception as e:
            print(f"[wecom] 解密失败: {e}")
            return PlainTextResponse("decrypt failed", status_code=400)
        fields = WeComChannel.parse_inbound_xml(plain_xml)
        msg_type = fields.get("MsgType", "")
        userid = fields.get("FromUserName", "")
        if not userid:
            return PlainTextResponse("success")
        if msg_type == "text":
            content = fields.get("Content", "")
            if await ch.try_confirm_reply(userid, content):
                return PlainTextResponse("success")
            allowed = ch.allowed_users()
            if allowed and userid not in allowed:
                print(f"[wecom] 忽略非白名单: {userid}")
                return PlainTextResponse("success")
            print(f"[wecom] 收到消息 ← {userid}: {content[:60]}")
            await ch.enqueue_text(userid, content)
        elif msg_type == "event" and fields.get("Event") == "subscribe":
            await ch.enqueue_text(userid, "你好")
        return PlainTextResponse("success")


def _active_wecom(ext_channels) -> WeComChannel | None:
    ch = ext_channels.get("wecom")
    if ch is None or not isinstance(ch, WeComChannel):
        return None
    if not ch.corp_id or not ch.secret or not ch.agent_id:
        return None
    return ch
