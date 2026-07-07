"""邮件 MIME 构建回归。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from channels.email_mime import apply_mail_headers, body_is_html, make_text_part
from email.mime.text import MIMEText


def test_body_is_html_detects_html():
    assert body_is_html("<html><body>hi</body></html>")
    assert body_is_html("  <div>hello</div>")
    assert not body_is_html("纯文本Body text")
    assert not body_is_html("")


def test_make_text_part_html_subtype():
    part = make_text_part("<html><body>测试</body></html>")
    assert part.get_content_type() == "text/html"
    assert "utf-8" in part.get_content_charset().lower()


def test_make_text_part_plain_subtype():
    part = make_text_part("你好，Captain")
    assert part.get_content_type() == "text/plain"


def test_apply_mail_headers_encodes_chinese_subject():
    msg = MIMEText("x", "plain", "utf-8")
    apply_mail_headers(msg, from_addr="a@qq.com", to_addr="b@outlook.com", subject="AI日报 · 2026年7月4日")
    subj = msg["Subject"]
    assert subj
    assert "AI" in subj or "2026" in subj  # encoded form still decodable
