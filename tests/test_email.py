"""邮件渠道回归 —— 发件人白名单(只听自己/指定名单)。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from channels.email_channel import EmailChannel


def test_allowlist_defaults_to_self():
    ch = EmailChannel(user="me@qq.com", password="x")
    assert ch.allowed == {"me@qq.com"}


def test_allowlist_from_env():
    os.environ["EMAIL_ALLOWED_SENDERS"] = "A@x.com, b@Y.com"
    try:
        ch = EmailChannel(user="me@qq.com", password="x")
        assert ch.allowed == {"a@x.com", "b@y.com"}
    finally:
        del os.environ["EMAIL_ALLOWED_SENDERS"]


def test_allowlist_empty_when_no_user():
    os.environ.pop("EMAIL_ALLOWED_SENDERS", None)
    os.environ.pop("EMAIL_USER", None)
    ch = EmailChannel(user="", password="")
    assert ch.allowed == set()
