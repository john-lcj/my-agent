"""邮件渠道回归 —— 发件人白名单(只听自己/指定名单)。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from channels.email_channel import EmailChannel, infer_email_servers


def test_infer_email_servers_qq():
    assert infer_email_servers("me@qq.com") == ("imap.qq.com", "smtp.qq.com", 993, 465)


def test_infer_email_servers_unknown():
    assert infer_email_servers("me@example.com") == ("", "", 993, 465)


def test_email_channel_autofills_hosts_from_user():
    os.environ.pop("EMAIL_IMAP_HOST", None)
    os.environ.pop("EMAIL_SMTP_HOST", None)
    ch = EmailChannel(user="me@qq.com", password="x")
    assert ch.imap_host == "imap.qq.com"
    assert ch.smtp_host == "smtp.qq.com"


def test_test_connection_rejects_missing_imap_host():
    os.environ.pop("EMAIL_IMAP_HOST", None)
    os.environ.pop("EMAIL_SMTP_HOST", None)
    ch = EmailChannel(user="me@example.com", password="x")
    result = ch.test_connection()
    assert result["ok"] is False
    assert "IMAP" in result["error"]


def test_allowlist_defaults_to_self():
    # 隔离 env:其它测试 import server.app 触发 load_dotenv 会灌入真实 EMAIL_ALLOWED_SENDERS
    os.environ.pop("EMAIL_ALLOWED_SENDERS", None)
    os.environ.pop("EMAIL_ALLOWED_RECIPIENTS", None)
    ch = EmailChannel(user="me@qq.com", password="x")
    assert ch.allowed_senders() == {"me@qq.com"}


def test_allowlist_from_env_includes_self():
    """配了白名单 + 始终包含自己(主人从 agent 邮箱发任务也能处理)。"""
    os.environ["EMAIL_ALLOWED_SENDERS"] = "A@x.com, b@Y.com"
    try:
        ch = EmailChannel(user="me@qq.com", password="x")
        assert ch.allowed_senders() == {"a@x.com", "b@y.com", "me@qq.com"}
    finally:
        del os.environ["EMAIL_ALLOWED_SENDERS"]


def test_allowlist_empty_when_no_user():
    os.environ.pop("EMAIL_ALLOWED_SENDERS", None)
    os.environ.pop("EMAIL_USER", None)
    ch = EmailChannel(user="", password="")
    assert ch.allowed_senders() == set()
