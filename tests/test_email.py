"""邮件渠道回归 —— 发件人白名单(只听自己/指定名单)。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from channels.email_channel import EmailChannel


def test_allowlist_defaults_to_self():
    # 隔离 env:其它测试 import server.app 触发 load_dotenv 会灌入真实 EMAIL_ALLOWED_SENDERS
    os.environ.pop("EMAIL_ALLOWED_SENDERS", None)
    ch = EmailChannel(user="me@qq.com", password="x")
    assert ch.allowed == {"me@qq.com"}


def test_allowlist_from_env_includes_self():
    """配了白名单 + 始终包含自己(主人从 agent 邮箱发任务也能处理)。"""
    os.environ["EMAIL_ALLOWED_SENDERS"] = "A@x.com, b@Y.com"
    try:
        ch = EmailChannel(user="me@qq.com", password="x")
        assert ch.allowed == {"a@x.com", "b@y.com", "me@qq.com"}
    finally:
        del os.environ["EMAIL_ALLOWED_SENDERS"]


def test_allowlist_empty_when_no_user():
    os.environ.pop("EMAIL_ALLOWED_SENDERS", None)
    os.environ.pop("EMAIL_USER", None)
    ch = EmailChannel(user="", password="")
    assert ch.allowed == set()
