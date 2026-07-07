"""企业微信自建应用渠道 —— 回调收消息 + API 发消息。"""
from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET

from core.types import CapabilityCall, Decision, Event, EventType, Identity


class WeComChannel:
    name = "wecom"

    def __init__(
        self,
        corp_id: str = "",
        agent_id: str = "",
        secret: str = "",
        token: str = "",
        aes_key: str = "",
    ) -> None:
        self.corp_id = (corp_id or os.environ.get("WECOM_CORP_ID", "")).strip()
        self.agent_id = (agent_id or os.environ.get("WECOM_AGENT_ID", "")).strip()
        self.secret = secret or os.environ.get("WECOM_SECRET", "")
        self.token = token or os.environ.get("WECOM_TOKEN", "")
        self.aes_key = aes_key or os.environ.get("WECOM_AES_KEY", "")
        self._inbox: asyncio.Queue[tuple[str, str] | None] = asyncio.Queue()
        self._pending_confirm: dict[str, asyncio.Future] = {}
        self._current_user: str = ""
        self._reply_sent: bool = False
        self._outbound_tasks: set[asyncio.Task] = set()
        self._access_token: str = ""
        self._token_exp: float = 0.0
        self._loop: asyncio.AbstractEventLoop | None = None

    def allowed_users(self) -> set[str]:
        raw = os.environ.get("WECOM_ALLOWED_USERS", "").strip()
        users = {u.strip() for u in raw.replace("，", ",").split(",") if u.strip()}
        return users

    async def enqueue_text(self, userid: str, text: str) -> None:
        if not userid or not (text or "").strip():
            return
        await self._inbox.put((userid, text.strip()))

    async def receive(self) -> str | None:
        item = await self._inbox.get()
        if item is None:
            return None
        userid, body = item
        self._current_user = userid
        return body

    async def mark_idle(self) -> None:
        self._current_user = ""

    async def flush_outbound(self) -> None:
        pending = list(self._outbound_tasks)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    def emit(self, event: Event) -> None:
        if not self._current_user:
            return
        if event.type == EventType.ASSISTANT_MESSAGE:
            self._reply_sent = True
            text = event.payload.get("text", "")
            task = asyncio.get_event_loop().create_task(
                self.send_text(self._current_user, text)
            )
            self._outbound_tasks.add(task)
            task.add_done_callback(self._outbound_tasks.discard)
        elif event.type == EventType.ERROR:
            self._reply_sent = True
            msg = event.payload.get("message", "")
            task = asyncio.get_event_loop().create_task(
                self.send_text(self._current_user, f"⚠️ {msg}")
            )
            self._outbound_tasks.add(task)
            task.add_done_callback(self._outbound_tasks.discard)

    async def confirm(self, call: CapabilityCall, decision: Decision, reason: str = "") -> bool:
        if not self._current_user:
            return False
        cid = uuid.uuid4().hex[:6].upper()
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_confirm[cid] = fut
        body = (
            f"需要确认操作:\n能力 {call.name}\n"
            f"回复 Y {cid} 确认 / N {cid} 拒绝\n60 秒未回复将拒绝。"
        )
        if reason:
            body += f"\n原因: {reason}"
        await self.send_text(self._current_user, body)
        try:
            return await asyncio.wait_for(fut, timeout=60.0)
        except asyncio.TimeoutError:
            return False
        finally:
            self._pending_confirm.pop(cid, None)

    def identity(self) -> Identity:
        return Identity(
            subject_id=self._current_user or "wecom",
            agent_name="main",
            channel="wecom",
        )

    async def try_confirm_reply(self, userid: str, text: str) -> bool:
        import re

        m = re.search(r"^([YNyn])\s+([A-F0-9]{6})\b", (text or "").strip())
        if not m:
            return False
        ok = m.group(1).upper() == "Y"
        cid = m.group(2).upper()
        fut = self._pending_confirm.get(cid)
        if fut and not fut.done():
            fut.set_result(ok)
            return True
        return False

    async def _get_access_token(self) -> str:
        now = time.time()
        if self._access_token and now < self._token_exp - 60:
            return self._access_token
        qs = urllib.parse.urlencode({"corpid": self.corp_id, "corpsecret": self.secret})
        url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?{qs}"
        data = await asyncio.get_event_loop().run_in_executor(None, self._http_get_json, url)
        if int(data.get("errcode", -1)) != 0:
            raise RuntimeError(data.get("errmsg") or "gettoken failed")
        self._access_token = str(data.get("access_token") or "")
        self._token_exp = now + float(data.get("expires_in") or 7200)
        return self._access_token

    def _http_get_json(self, url: str) -> dict:
        try:
            with urllib.request.urlopen(url, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(body[:300]) from e

    def _http_post_json(self, url: str, payload: dict) -> dict:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(body[:300]) from e

    async def send_text(self, userid: str, content: str) -> None:
        if not userid or not (content or "").strip():
            return
        allowed = self.allowed_users()
        if allowed and userid not in allowed:
            print(f"[wecom] 忽略非白名单用户: {userid}")
            return
        try:
            token = await self._get_access_token()
            url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"
            payload = {
                "touser": userid,
                "msgtype": "text",
                "agentid": int(self.agent_id),
                "text": {"content": (content or "")[:4000]},
                "safe": 0,
            }
            data = await asyncio.get_event_loop().run_in_executor(
                None, self._http_post_json, url, payload,
            )
            if int(data.get("errcode", -1)) != 0:
                print(f"[wecom] 发送失败: {data.get('errmsg')}")
                return
            print(f"[wecom] 已回复 → {userid}")
        except Exception as e:
            print(f"[wecom] 发送异常: {e}")

    def test_connection(self) -> dict:
        result = {"ok": False, "token": False, "send": False, "error": ""}
        if not self.corp_id:
            result["error"] = "请填写企业 ID (CorpId)"
            return result
        if not self.secret:
            result["error"] = "请填写应用 Secret"
            return result
        if not self.agent_id:
            result["error"] = "请填写 AgentId"
            return result
        try:
            qs = urllib.parse.urlencode({"corpid": self.corp_id, "corpsecret": self.secret})
            data = self._http_get_json(f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?{qs}")
            if int(data.get("errcode", -1)) != 0:
                result["error"] = data.get("errmsg") or "gettoken 失败"
                return result
            result["token"] = True
            result["ok"] = True
        except Exception as e:
            result["error"] = str(e)[:200]
        return result

    @staticmethod
    def parse_inbound_xml(xml_text: str) -> dict[str, str]:
        root = ET.fromstring(xml_text)
        out: dict[str, str] = {}
        for child in root:
            out[child.tag] = (child.text or "").strip()
        return out
