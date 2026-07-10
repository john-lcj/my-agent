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


def test_channel_store_autofills_on_update(tmp_path, monkeypatch):
    monkeypatch.setenv("CAPTAIN_USE_KEYCHAIN", "0")
    path = tmp_path / "channels.json"
    store = ChannelConfigStore(path=str(path))
    store.update("email", {"user": "me@163.com", "password": "secret"})
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["email"]["imap"] == "imap.163.com"
    assert "password" not in saved["email"]
    assert saved["email"]["password_ref"].startswith("vault:")
    assert os.environ["EMAIL_IMAP_HOST"] == "imap.163.com"


def test_channel_store_migrates_legacy_plaintext(tmp_path, monkeypatch):
    monkeypatch.setenv("CAPTAIN_USE_KEYCHAIN", "0")
    path = tmp_path / "channels.json"
    path.write_text(
        json.dumps({
            "email": {"user": "me@qq.com", "password": "legacy-secret"},
            "slack": {"bot_token": "legacy-slack", "team": "main"},
        }),
        encoding="utf-8",
    )

    store = ChannelConfigStore(path=str(path))

    saved = json.loads(path.read_text(encoding="utf-8"))
    assert "password" not in saved["email"]
    assert "bot_token" not in saved["slack"]
    assert "legacy-secret" not in path.read_text(encoding="utf-8")
    assert "legacy-slack" not in path.read_text(encoding="utf-8")
    assert saved["email"]["password_ref"].startswith("vault:")
    assert saved["slack"]["bot_token_ref"].startswith("vault:")
    assert os.environ["EMAIL_PASS"] == "legacy-secret"
    assert store.get_masked()["email"]["password"] == "******"


def test_channel_store_migrates_env_file_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("CAPTAIN_USE_KEYCHAIN", "0")
    path = tmp_path / "channels.json"
    env_path = tmp_path / ".env"
    env_path.write_text(
        "EMAIL_USER=me@example.com\n"
        "EMAIL_PASS=mail-secret\n"
        "ONEBOT_ACCESS_TOKEN=qq-secret\n"
        "DEEPSEEK_API_KEY=model-secret\n",
        encoding="utf-8",
    )

    ChannelConfigStore(path=str(path), env_path=str(env_path))

    saved = json.loads(path.read_text(encoding="utf-8"))
    env_text = env_path.read_text(encoding="utf-8")
    assert saved["email"]["password_ref"].startswith("vault:")
    assert saved["qq"]["access_token_ref"].startswith("vault:")
    assert "mail-secret" not in env_text
    assert "qq-secret" not in env_text
    assert "EMAIL_PASS=" not in env_text
    assert "ONEBOT_ACCESS_TOKEN=" not in env_text
    assert "DEEPSEEK_API_KEY=model-secret" in env_text
    assert os.environ["EMAIL_PASS"] == "mail-secret"
    assert os.environ["ONEBOT_ACCESS_TOKEN"] == "qq-secret"


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
