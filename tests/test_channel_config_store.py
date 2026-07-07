"""频道配置持久化回归 —— 邮件服务器自动补全。"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from channels.config_store import ChannelConfigStore, finalize_email_cfg, apply_email_allow_env


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


def test_channel_store_syncs_allowlist_to_recipients(tmp_path):
    path = tmp_path / "channels.json"
    store = ChannelConfigStore(path=str(path))
    store.update("email", {
        "user": "me@qq.com",
        "password": "secret",
        "allowed": "boss@outlook.com",
    })
    assert os.environ["EMAIL_ALLOWED_SENDERS"] == "boss@outlook.com"
    assert "boss@outlook.com" in os.environ["EMAIL_ALLOWED_RECIPIENTS"]
    assert "me@qq.com" in os.environ["EMAIL_ALLOWED_RECIPIENTS"]


def test_channel_store_clears_allowlist_env_when_empty(tmp_path):
    path = tmp_path / "channels.json"
    store = ChannelConfigStore(path=str(path))
    store.update("email", {"user": "me@qq.com", "password": "secret", "allowed": "a@x.com"})
    store.update("email", {"user": "me@qq.com", "allowed": ""})
    assert "EMAIL_ALLOWED_SENDERS" not in os.environ
    assert "EMAIL_ALLOWED_RECIPIENTS" not in os.environ


def test_channel_store_wecom_config(tmp_path):
    path = tmp_path / "channels.json"
    store = ChannelConfigStore(path=str(path))
    store.update("wecom", {
        "corp_id": "wwabc",
        "agent_id": "1000002",
        "secret": "sec",
        "token": "tok",
        "aes_key": "key43",
        "allowed": "ZhangSan, LiSi",
    })
    assert store.is_configured("wecom")
    assert os.environ["WECOM_CORP_ID"] == "wwabc"
    assert os.environ["WECOM_ALLOWED_USERS"] == "ZhangSan, LiSi"
    masked = store.get_masked()
    assert masked["wecom"]["secret"] == "******"
    assert masked["wecom"]["corp_id"] == "wwabc"
