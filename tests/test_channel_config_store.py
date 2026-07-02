"""频道配置持久化回归 —— 邮件服务器自动补全。"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from channels.config_store import ChannelConfigStore, finalize_email_cfg


def test_finalize_email_cfg_from_qq_user(tmp_path):
    cfg = finalize_email_cfg({"user": "me@qq.com", "password": "x"})
    assert cfg["imap"] == "imap.qq.com"
    assert cfg["smtp"] == "smtp.qq.com"
    assert cfg["imap_port"] == "993"


def test_finalize_email_cfg_strips_localhost():
    cfg = finalize_email_cfg({"user": "me@qq.com", "imap": "localhost", "smtp": "127.0.0.1"})
    assert cfg["imap"] == "imap.qq.com"
    assert cfg["smtp"] == "smtp.qq.com"


def test_channel_store_autofills_on_update(tmp_path):
    path = tmp_path / "channels.json"
    store = ChannelConfigStore(path=str(path))
    store.update("email", {"user": "me@163.com", "password": "secret"})
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["email"]["imap"] == "imap.163.com"
    assert os.environ["EMAIL_IMAP_HOST"] == "imap.163.com"
