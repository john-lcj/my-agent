"""邮件 MIME 构建 —— HTML/纯文本自动识别 + 中文主题 UTF-8 编码。"""
from __future__ import annotations

import re
from email.header import Header
from email.mime.text import MIMEText


def body_is_html(body: str) -> bool:
    s = (body or "").lstrip().lower()
    if not s:
        return False
    if s.startswith("<!doctype html") or s.startswith("<html"):
        return True
    return bool(re.search(r"<\s*(html|body|div|p|h[1-6]|table|span)\b", s[:800], re.I))


def make_text_part(body: str) -> MIMEText:
    subtype = "html" if body_is_html(body) else "plain"
    return MIMEText(body or "", subtype, "utf-8")


def apply_mail_headers(msg, *, from_addr: str, to_addr: str, subject: str) -> None:
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = str(Header(subject or "(无主题)", "utf-8"))
