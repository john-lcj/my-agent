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

import json
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

from channels.email_mime import apply_mail_headers, make_text_part
from typing import Optional

from core.types import CapabilityCall, Decision, Event, EventType, Identity

# 常见邮箱 IMAP/SMTP 预设(主机留空时按账号域名自动补全)
_EMAIL_SERVER_PRESETS: dict[str, tuple[str, str, int, int]] = {
    "qq.com": ("imap.qq.com", "smtp.qq.com", 993, 465),
    "foxmail.com": ("imap.qq.com", "smtp.qq.com", 993, 465),
    "163.com": ("imap.163.com", "smtp.163.com", 993, 465),
    "126.com": ("imap.126.com", "smtp.126.com", 993, 465),
    "yeah.net": ("imap.yeah.net", "smtp.yeah.net", 993, 465),
    "gmail.com": ("imap.gmail.com", "smtp.gmail.com", 993, 465),
    "outlook.com": ("outlook.office365.com", "smtp.office365.com", 993, 587),
    "hotmail.com": ("outlook.office365.com", "smtp.office365.com", 993, 587),
    "live.com": ("outlook.office365.com", "smtp.office365.com", 993, 587),
    "icloud.com": ("imap.mail.me.com", "smtp.mail.me.com", 993, 587),
    "exmail.qq.com": ("imap.exmail.qq.com", "smtp.exmail.qq.com", 993, 465),
}


def infer_email_servers(user: str) -> tuple[str, str, int, int]:
    """根据邮箱域名推断 IMAP/SMTP 主机与端口;未知域名返回空主机 + 默认端口。"""
    domain = user.rsplit("@", 1)[-1].strip().lower() if "@" in user else ""
    return _EMAIL_SERVER_PRESETS.get(domain, ("", "", 993, 465))


def _env_port(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _clean_host(host: str) -> str:
    h = (host or "").strip()
    return "" if h.lower() in {"", "localhost", "127.0.0.1", "::1"} else h


def _imap_part_str(item) -> str:
    if isinstance(item, tuple):
        item = item[0]
    if isinstance(item, bytes):
        return item.decode(errors="replace")
    return str(item or "")


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
        self.user = (user or os.environ.get("EMAIL_USER", "")).strip()
        self.password = password or os.environ.get("EMAIL_PASS", "")
        self.imap_host = _clean_host(imap_host or os.environ.get("EMAIL_IMAP_HOST", ""))
        self.smtp_host = _clean_host(smtp_host or os.environ.get("EMAIL_SMTP_HOST", ""))
        self.imap_port = imap_port if imap_port else _env_port("EMAIL_IMAP_PORT", 993)
        self.smtp_port = smtp_port if smtp_port else _env_port("EMAIL_SMTP_PORT", 465)
        if self.user and (not self.imap_host or not self.smtp_host):
            ih, sh, ip, sp = infer_email_servers(self.user)
            if ih and not self.imap_host:
                self.imap_host = ih
            if sh and not self.smtp_host:
                self.smtp_host = sh
            if not os.environ.get("EMAIL_IMAP_PORT", "").strip():
                self.imap_port = ip
            if not os.environ.get("EMAIL_SMTP_PORT", "").strip():
                self.smtp_port = sp
        self.poll_sec = poll_sec or float(os.environ.get("EMAIL_POLL_SEC", "30"))

        self._inbox: asyncio.Queue[Optional[tuple[str, str, str, str]]] = asyncio.Queue()
        self._pending_confirm: dict[str, asyncio.Future] = {}
        self._current_sender: str = ""
        self._current_uid: str = ""
        self._current_msg_id: str = ""
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._poll_task: Optional[asyncio.Task] = None
        self._processed_ids: set[str] = self._load_processed_ids()
        self._queued_keys: set[str] = set()
        self._outbound_tasks: set[asyncio.Task] = set()
        self._reply_sent: bool = False
        self._inflight_keys: set[str] = set()

    def _mail_key(self, uid: str, msg_id: str) -> str:
        mid = (msg_id or "").strip()
        if mid:
            return f"mid:{mid}"
        return f"uid:{uid}"

    def _release_inflight(self, uid: str = "", msg_id: str = "") -> None:
        key = self._mail_key(uid or self._current_uid, msg_id or self._current_msg_id)
        self._inflight_keys.discard(key)

    def allowed_senders(self) -> set[str]:
        """入站白名单:每次从 env 读取,保存配置后无需重启渠道即可生效。"""
        raw_allow = os.environ.get("EMAIL_ALLOWED_SENDERS", "").strip()
        allowed = {a.strip().lower() for a in raw_allow.split(",") if a.strip()}
        if self.user:
            allowed.add(self.user.lower())
        return allowed

    def _processed_ids_path(self) -> str:
        root = os.environ.get("AGENT_WORKSPACE_ROOT", "") or os.getcwd()
        return os.path.join(root, "logs", "email_processed.json")

    def _load_processed_ids(self) -> set[str]:
        path = self._processed_ids_path()
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return {str(x).strip() for x in data if str(x).strip()}
        except Exception:
            pass
        return set()

    def _queue_key(self, uid: str, msg_id: str) -> str:
        mid = (msg_id or "").strip()
        if mid:
            return f"mid:{mid}"
        return f"uid:{uid}"

    def _release_queue_key(self, uid: str, msg_id: str) -> None:
        self._queued_keys.discard(self._queue_key(uid, msg_id))

    async def release_current_queued(self) -> None:
        """处理失败时释放去重锁,下轮轮询可重试。"""
        self._release_queue_key(self._current_uid, self._current_msg_id)

    async def flush_outbound(self) -> None:
        """等待 emit 触发的 SMTP 回信完成。"""
        pending = list(self._outbound_tasks)
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    def _save_processed_id(self, msg_id: str) -> None:
        mid = (msg_id or "").strip()
        if not mid:
            return
        self._processed_ids.add(mid)
        path = self._processed_ids_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(sorted(self._processed_ids)[-500:], f, ensure_ascii=False)
        except Exception:
            pass

    # ── Channel 协议 ───────────────────────────────────────────────────────────

    async def receive(self) -> Optional[str]:
        """等待下一封入站邮件,返回邮件Body text。"""
        item = await self._inbox.get()
        if item is None:
            return None
        sender, body, uid, msg_id = item
        self._current_sender = sender
        self._current_uid = uid
        self._current_msg_id = msg_id
        return body

    async def mark_current_seen(self) -> None:
        """处理成功后标记 IMAP 已读并记录 Message-ID(失败则不标,下轮可重试)。"""
        uid = (self._current_uid or "").strip()
        msg_id = (self._current_msg_id or "").strip()
        if uid:
            loop = self._loop or asyncio.get_running_loop()
            await loop.run_in_executor(None, self._mark_seen_sync, uid)
        if msg_id:
            self._save_processed_id(msg_id)
        self._release_queue_key(uid, msg_id)
        self._current_uid = ""
        self._current_msg_id = ""

    def emit(self, event: Event) -> None:
        if not self._current_sender:
            return
        if event.type == EventType.ASSISTANT_MESSAGE:
            self._reply_sent = True
            text = event.payload.get("text", "")
            task = asyncio.get_event_loop().create_task(
                self._send_email(self._current_sender, "Re: Agent 回复", text)
            )
            self._outbound_tasks.add(task)
            task.add_done_callback(self._outbound_tasks.discard)
        elif event.type == EventType.ERROR:
            self._reply_sent = True
            msg = event.payload.get("message", "")
            task = asyncio.get_event_loop().create_task(
                self._send_email(self._current_sender, "Agent 错误", msg)
            )
            self._outbound_tasks.add(task)
            task.add_done_callback(self._outbound_tasks.discard)

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
        if self._poll_task and not self._poll_task.done():
            return
        self._loop = asyncio.get_running_loop()
        self._poll_task = self._loop.create_task(self._poll_loop())

    def _enqueue_inbox(self, item: tuple[str, str, str, str]) -> None:
        self._inbox.put_nowait(item)
        print(f"[email] 已入队 depth={self._inbox.qsize()} ← {item[0]}")

    async def stop_polling(self) -> None:
        """停止轮询(渠道重启/关闭时必调,避免旧队列与新区脱节)。"""
        task = self._poll_task
        self._poll_task = None
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _poll_loop(self) -> None:
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self._recover_unseen_allowlist)
        except Exception as e:
            print(f"[email] 启动补捞异常: {e}")
        while True:
            try:
                await loop.run_in_executor(None, self._fetch_new)
            except Exception as e:
                print(f"[email] 轮询异常: {e}")
            await asyncio.sleep(self.poll_sec)

    def _mark_seen_sync(self, uid: str) -> None:
        ctx = ssl.create_default_context()
        with imaplib.IMAP4_SSL(self.imap_host, self.imap_port, ssl_context=ctx) as imap:
            imap.login(self.user, self.password)
            imap.select("INBOX")
            imap.store(uid, "+FLAGS", "\\Seen")

    def _recover_unseen_allowlist(self) -> None:
        """启动时把白名单发件人近 48h 内未读信补标 UNSEEN(修复曾被误标已读但未回信的)。"""
        import datetime
        since = (datetime.date.today() - datetime.timedelta(days=2)).strftime("%d-%b-%Y")
        allowed = self.allowed_senders() - {self.user.lower()} if self.user else self.allowed_senders()
        if not allowed:
            return
        ctx = ssl.create_default_context()
        with imaplib.IMAP4_SSL(self.imap_host, self.imap_port, ssl_context=ctx) as imap:
            imap.login(self.user, self.password)
            imap.select("INBOX")
            for addr in sorted(allowed):
                try:
                    _, data = imap.search(None, "FROM", f'"{addr}"', "SINCE", since)
                except Exception:
                    continue
                ids = data[0].split() if data and data[0] else []
                for mid in ids[-20:]:
                    _, raw = imap.fetch(mid, "(RFC822)")
                    msg = _email_lib.message_from_bytes(raw[0][1])
                    msg_id = (msg.get("Message-ID") or "").strip()
                    if msg_id and msg_id in self._processed_ids:
                        continue
                    if msg.get("X-Agent-Autoreply"):
                        continue
                    subj = _decode_header(msg.get("Subject", ""))
                    if subj.startswith("Re: Agent") or "[Captain Mission" in subj:
                        continue
                    _, fl = imap.fetch(mid, "(FLAGS)")
                    flags = _imap_part_str(fl[0] if fl else b"")
                    if "\\Seen" not in flags:
                        continue
                    imap.store(mid, "-FLAGS", "\\Seen")
                    print(f"[email] 补捞:重新标未读 ← {addr}:{subj[:40]}")

    def _fetch_new(self) -> None:
        """同步 IMAP 拉取 UNSEEN 邮件(在 executor 线程里运行)。"""
        ctx = ssl.create_default_context()
        with imaplib.IMAP4_SSL(self.imap_host, self.imap_port, ssl_context=ctx) as imap:
            imap.login(self.user, self.password)
            imap.select("INBOX")
            _, msg_ids = imap.search(None, "UNSEEN")
            ids = msg_ids[0].split() if msg_ids and msg_ids[0] else []
            if ids:
                print(f"[email] 本轮发现 {len(ids)} 封未读")
            for mid in ids:
                _, data = imap.fetch(mid, "(RFC822)")
                raw = data[0][1] if data and data[0] else b""
                msg = _email_lib.message_from_bytes(raw)

                # 跳过本 agent 自己发出的回信(防自问自答死循环)
                if msg.get("X-Agent-Autoreply"):
                    try:
                        imap.store(mid, "+FLAGS", "\\Seen")
                    except Exception:
                        pass
                    print("[email] 跳过自己的回信(防循环)")
                    continue

                sender = _parse_addr(msg.get("From", ""))
                subject = _decode_header(msg.get("Subject", ""))
                body = _extract_body(msg)
                msg_id = (msg.get("Message-ID") or "").strip()
                if msg_id and msg_id in self._processed_ids:
                    try:
                        imap.store(mid, "+FLAGS", "\\Seen")
                    except Exception:
                        pass
                    continue

                # 白名单过滤:非许可发件人直接忽略(防陌生人驱使 agent / 烧额度)
                allowed = self.allowed_senders()
                if allowed and sender.strip().lower() not in allowed:
                    try:
                        imap.store(mid, "+FLAGS", "\\Seen")
                    except Exception:
                        pass
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
                    try:
                        imap.store(mid, "+FLAGS", "\\Seen")
                    except Exception:
                        pass
                    continue

                # 普通消息 —— 入队去重;处理成功后再 mark_current_seen
                uid = mid.decode() if isinstance(mid, bytes) else str(mid)
                qkey = self._queue_key(uid, msg_id)
                if qkey in self._queued_keys:
                    continue
                self._queued_keys.add(qkey)
                print(f"[email] 收到来信 ← {sender}:{subject[:40]}")
                if self._loop is not None:
                    self._loop.call_soon_threadsafe(
                        self._enqueue_inbox,
                        (sender, f"[Email subject:{subject}]\n{body}", uid, msg_id),
                    )
                else:
                    print("[email] 警告:_loop 未就绪,邮件未入队")
            imap.logout()

    async def _send_email(self, to: str, subject: str, body: str,
                          attachments: list[str] | None = None) -> None:
        # 永不让发信异常冒泡(否则 asyncio 报 "Task exception was never retrieved" 刷屏)
        try:
            await asyncio.get_event_loop().run_in_executor(
                None, self._send_sync, to, subject, body, attachments or []
            )
        except Exception as e:
            print(f"[email] 回信失败(已忽略,不重试):{e}")

    def _send_sync(self, to: str, subject: str, body: str,
                   attachments: list[str] | None = None) -> None:
        attachments = [p for p in (attachments or []) if os.path.isfile(p)][:5]
        if attachments:
            from email.mime.multipart import MIMEMultipart
            from email.mime.application import MIMEApplication
            msg = MIMEMultipart()
            msg.attach(make_text_part(body))
            for path in attachments:
                try:
                    if os.path.getsize(path) > 10 * 1024 * 1024:  # 单附件上限 10MB
                        continue
                    with open(path, "rb") as f:
                        part = MIMEApplication(f.read())
                    part.add_header("Content-Disposition", "attachment",
                                    filename=os.path.basename(path))
                    msg.attach(part)
                except Exception:
                    continue
        else:
            msg = make_text_part(body)
        apply_mail_headers(msg, from_addr=self.user, to_addr=to, subject=subject)
        # 自动回信打标记:收信端见到此头就跳过,避免"自己回信→自己又读到→再回"的死循环。
        msg["X-Agent-Autoreply"] = "1"
        ctx = ssl.create_default_context()
        # QQ SMTP 偶发断连(尤其被限流后),重试一次;仍失败则抛给上层安静记录。
        last_err: Exception | None = None
        for attempt in range(2):
            try:
                with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, context=ctx, timeout=20) as smtp:
                    smtp.login(self.user, self.password)
                    smtp.send_message(msg)
                print(f"[email] 已回信 → {to}:{subject[:40]}")
                return
            except Exception as e:
                last_err = e
                time.sleep(2)
        if last_err:
            raise last_err

    def test_connection(self) -> dict:
        """同步验证 IMAP + SMTP 登录,返回 {ok, imap, smtp, error, imap_target, smtp_target}。"""
        result = {
            "ok": False, "imap": False, "smtp": False, "error": "",
            "imap_target": "", "smtp_target": "",
        }
        if not self.user:
            result["error"] = "请填写邮箱账号"
            return result
        if not self.password:
            result["error"] = "请填写邮箱授权码（QQ/163 需用授权码，不是登录密码）"
            return result
        if not self.imap_host:
            result["error"] = (
                "IMAP 服务器未配置。"
                "请填写服务器地址（QQ: imap.qq.com，163: imap.163.com），"
                "或填写完整邮箱账号后保存再试"
            )
            return result
        if not self.smtp_host:
            result["error"] = (
                "SMTP 服务器未配置。"
                "请填写服务器地址（QQ: smtp.qq.com，163: smtp.163.com）"
            )
            return result
        result["imap_target"] = f"{self.imap_host}:{self.imap_port}"
        result["smtp_target"] = f"{self.smtp_host}:{self.smtp_port}"
        ctx = ssl.create_default_context()
        try:
            with imaplib.IMAP4_SSL(self.imap_host, self.imap_port, ssl_context=ctx, timeout=20) as imap:
                imap.login(self.user, self.password)
                imap.select("INBOX")
                imap.logout()
            result["imap"] = True
        except Exception as e:
            err = str(e)
            if "Connection refused" in err or "Errno 61" in err:
                result["error"] = (
                    f"IMAP 无法连接 {result['imap_target']}（连接被拒绝）。"
                    "请确认 IMAP 服务器地址是否正确，且邮箱已开启 IMAP 服务"
                )
            else:
                result["error"] = f"IMAP 失败 ({result['imap_target']}): {e}"
            return result
        try:
            with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, context=ctx, timeout=20) as smtp:
                smtp.login(self.user, self.password)
            result["smtp"] = True
        except Exception as e:
            result["error"] = f"SMTP 失败 ({result['smtp_target']}): {e}"
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
    """递归提取纯文本Body text,优先 text/plain。"""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                charset = part.get_content_charset() or "utf-8"
                return part.get_payload(decode=True).decode(charset, "replace")
    else:
        charset = msg.get_content_charset() or "utf-8"
        return msg.get_payload(decode=True).decode(charset, "replace")
    return ""
