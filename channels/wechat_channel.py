"""企业微信渠道(WeCom / 企业微信应用)。

接入方式:企业微信"自建应用" + 消息接收 webhook。
  1. 企业微信管理后台创建自建应用,开启"接收消息",填写本机 URL。
  2. 微信推送 POST 到 /webhook/wechat,本 channel 解密并入队。
  3. agent 回复时,调用企业微信 REST API 发送文本消息。

学习点:
  - 微信消息推送采用 AES 加密 + XML 格式(被动接收)。
  - access_token 有效期 7200 秒,自动刷新。
  - 软边界确认:推送一条确认消息给用户,等待回复 "y 确认码" / "n 确认码"。

配置(通过 .env):
  WECHAT_CORP_ID          企业 ID
  WECHAT_AGENT_ID         应用 AgentId
  WECHAT_SECRET           应用 Secret
  WECHAT_TOKEN            接收消息的 Token(消息验证用)
  WECHAT_ENCODING_AES_KEY 消息加密密钥(43位)
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
import uuid
import xml.etree.ElementTree as ET
from typing import Optional

from core.types import CapabilityCall, Decision, Event, EventType, Identity

_API_BASE = "https://qyapi.weixin.qq.com/cgi-bin"


class WeChatChannel:
    name = "wechat"

    def __init__(
        self,
        corp_id: str = "",
        agent_id: str = "",
        secret: str = "",
        token: str = "",
        aes_key: str = "",
    ) -> None:
        self.corp_id = corp_id or os.environ.get("WECHAT_CORP_ID", "")
        self.agent_id = agent_id or os.environ.get("WECHAT_AGENT_ID", "")
        self.secret = secret or os.environ.get("WECHAT_SECRET", "")
        self.token = token or os.environ.get("WECHAT_TOKEN", "")
        self.aes_key = aes_key or os.environ.get("WECHAT_ENCODING_AES_KEY", "")

        self._inbox: asyncio.Queue[Optional[tuple[str, str]]] = asyncio.Queue()
        self._pending_confirm: dict[str, asyncio.Future] = {}
        self._current_user: str = ""

        # access_token 缓存
        self._token_value: str = ""
        self._token_exp: float = 0.0

    # ── Channel 协议 ───────────────────────────────────────────────────────────

    async def receive(self) -> Optional[str]:
        item = await self._inbox.get()
        if item is None:
            return None
        user_id, text = item
        self._current_user = user_id
        return text

    def emit(self, event: Event) -> None:
        if not self._current_user:
            return
        if event.type == EventType.ASSISTANT_MESSAGE:
            text = event.payload.get("text", "")
            asyncio.get_event_loop().create_task(
                self._send_text(self._current_user, text)
            )
        elif event.type == EventType.ERROR:
            asyncio.get_event_loop().create_task(
                self._send_text(self._current_user, f"⚠️ 错误:{event.payload.get('message', '')}")
            )

    async def confirm(self, call: CapabilityCall, decision: Decision, reason: str = "") -> bool:
        if not self._current_user:
            return False
        confirm_id = uuid.uuid4().hex[:6].upper()
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_confirm[confirm_id] = future

        msg = (
            f"🔔 需要你确认:\n"
            f"能力: {call.name}\n"
            f"参数: {json.dumps(call.args, ensure_ascii=False)}\n"
            f"意图: {call.intent or '(未声明)'}\n"
            + (f"治理: {reason}\n" if reason else "") + "\n"
            f"回复  y {confirm_id}  确认\n"
            f"回复  n {confirm_id}  拒绝\n"
            f"⚠️ 60 秒内未回复将自动拒绝"
        )
        await self._send_text(self._current_user, msg)
        try:
            return await asyncio.wait_for(future, timeout=60.0)
        except asyncio.TimeoutError:
            return False
        finally:
            self._pending_confirm.pop(confirm_id, None)

    def identity(self) -> Identity:
        return Identity(
            subject_id=self._current_user or "wechat-user",
            agent_name="main",
            channel="wechat",
        )

    # ── Webhook 入口(由 server/app.py 调用)───────────────────────────────────

    async def handle_verification(self, params: dict) -> str:
        """GET 验证:微信服务器验证 URL 有效性,返回 echostr。"""
        msg_signature = params.get("msg_signature", "")
        timestamp = params.get("timestamp", "")
        nonce = params.get("nonce", "")
        echostr = params.get("echostr", "")

        # 签名验证
        if not _verify_signature(self.token, timestamp, nonce, "", msg_signature):
            return ""
        # 若配置了加密密钥则解密 echostr
        if self.aes_key and echostr:
            try:
                echostr = _aes_decrypt(echostr, self.aes_key, self.corp_id)
            except Exception:
                pass
        return echostr

    async def handle_message(self, body: bytes, params: dict) -> str:
        """POST 消息:解析/解密 XML 消息并入队。"""
        xml_str = body.decode("utf-8", "replace")
        try:
            root = ET.fromstring(xml_str)
        except ET.ParseError:
            return "fail"

        # 若加密则先解密
        encrypt_el = root.find("Encrypt")
        if encrypt_el is not None and self.aes_key:
            try:
                xml_str = _aes_decrypt(encrypt_el.text or "", self.aes_key, self.corp_id)
                root = ET.fromstring(xml_str)
            except Exception as e:
                return "fail"

        msg_type = _xml_text(root, "MsgType")
        if msg_type != "text":
            return "success"

        user_id = _xml_text(root, "FromUserName")
        content = _xml_text(root, "Content").strip()

        # 确认回复  "y ABCDEF" / "n ABCDEF"
        import re
        m = re.match(r"^([yYnN])\s+([A-F0-9]{6})$", content)
        if m:
            approved = m.group(1).upper() == "Y"
            cid = m.group(2)
            fut = self._pending_confirm.get(cid)
            if fut and not fut.done():
                fut.set_result(approved)
            return "success"

        self._inbox.put_nowait((user_id, content))
        return "success"

    # ── 发送消息 ───────────────────────────────────────────────────────────────

    async def _send_text(self, to_user: str, content: str) -> None:
        token = await self._get_token()
        if not token:
            return
        url = f"{_API_BASE}/message/send?access_token={token}"
        payload = {
            "touser": to_user,
            "msgtype": "text",
            "agentid": int(self.agent_id) if self.agent_id else 0,
            "text": {"content": content},
        }
        try:
            import aiohttp
            async with aiohttp.ClientSession() as s:
                await s.post(url, json=payload)
        except Exception as e:
            print(f"[wechat] 发送失败: {e}")

    async def _get_token(self) -> str:
        if self._token_value and time.time() < self._token_exp:
            return self._token_value
        url = f"{_API_BASE}/gettoken?corpid={self.corp_id}&corpsecret={self.secret}"
        try:
            import aiohttp
            async with aiohttp.ClientSession() as s:
                async with s.get(url) as r:
                    data = await r.json(content_type=None)
            self._token_value = data.get("access_token", "")
            self._token_exp = time.time() + data.get("expires_in", 7200) - 60
            return self._token_value
        except Exception as e:
            print(f"[wechat] 获取 token 失败: {e}")
            return ""


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def _xml_text(root: ET.Element, tag: str) -> str:
    el = root.find(tag)
    return (el.text or "") if el is not None else ""


def _verify_signature(token: str, timestamp: str, nonce: str, msg_encrypt: str, sig: str) -> bool:
    """微信签名校验(对外 webhook 安全的第一道关卡)。"""
    lst = sorted([token, timestamp, nonce, msg_encrypt])
    expected = hashlib.sha1("".join(lst).encode("utf-8")).hexdigest()
    return expected == sig


def _aes_decrypt(encrypt_str: str, aes_key_b64: str, corp_id: str) -> str:
    """解密企业微信 AES 消息(EncodingAESKey + PKCS7 填充)。"""
    import base64
    from Crypto.Cipher import AES  # pycryptodome

    key = base64.b64decode(aes_key_b64 + "=")
    ciphertext = base64.b64decode(encrypt_str)
    cipher = AES.new(key, AES.MODE_CBC, key[:16])
    decrypted = cipher.decrypt(ciphertext)
    # 去掉 PKCS7 填充 + 前 16 字节随机串 + 4 字节长度
    content = decrypted[16:]
    msg_len = int.from_bytes(content[:4], "big")
    xml_content = content[4: 4 + msg_len].decode("utf-8")
    return xml_content
