"""频道配置的服务端持久化 —— 让"在网页里填的频道配置"真正生效。

之前频道只读 .env、配置存在浏览器 localStorage 里,两边对不上,所以"跑不通"。
这里把配置落到 logs/channels.json,并在加载时写进 os.environ,这样各 Channel 的
__init__(本就从 env 读)无需改动即可拿到配置。

字段映射(前端 key -> 环境变量):见 FIELD_MAP。密码类字段在读取(对外)时打码。
"""
from __future__ import annotations

import json
import os

# 前端字段 -> 环境变量名
FIELD_MAP = {
    "email": {
        "imap": "EMAIL_IMAP_HOST", "smtp": "EMAIL_SMTP_HOST",
        "user": "EMAIL_USER", "password": "EMAIL_PASS",
    },
    "wechat": {
        "corp_id": "WECHAT_CORP_ID", "agent_id": "WECHAT_AGENT_ID",
        "secret": "WECHAT_SECRET", "token": "WECHAT_TOKEN", "aes_key": "WECHAT_AES_KEY",
    },
    "qq": {
        "app_id": "QQ_BOT_APP_ID",
        "app_secret": "QQ_BOT_SECRET",
        "sandbox": "QQ_BOT_SANDBOX",
    },
    "slack": {
        "bot_token": "SLACK_BOT_TOKEN", "signing_secret": "SLACK_SIGNING_SECRET",
    },
    "telegram": {
        "bot_token": "TELEGRAM_BOT_TOKEN",
    },
}
SECRET_FIELDS = {"password", "secret", "token", "aes_key", "app_secret"}


class ChannelConfigStore:
    def __init__(self, path: str = "logs/channels.json") -> None:
        self.path = path
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._data: dict = self._read()
        if self._migrate_qq_fields():
            self._write()
        self.apply_to_env()

    def _read(self) -> dict:
        if not os.path.isfile(self.path):
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
        except Exception:
            return {}
        return self._normalize_legacy(data)

    @staticmethod
    def _normalize_legacy(data: dict) -> dict:
        """读盘时合并旧字段 token/secret → app_secret。"""
        qq = data.get("qq")
        if not isinstance(qq, dict):
            return data
        if not qq.get("app_secret"):
            legacy = qq.get("secret") or qq.get("token") or ""
            if legacy:
                qq["app_secret"] = legacy
        return data

    def _migrate_qq_fields(self) -> bool:
        """落盘为 app_id + app_secret 两项,去掉历史 token/secret 字段。"""
        qq = self._data.get("qq")
        if not isinstance(qq, dict):
            return False
        changed = False
        if not qq.get("app_secret"):
            legacy = qq.get("secret") or qq.get("token") or ""
            if legacy:
                qq["app_secret"] = legacy
                changed = True
        for key in ("token", "secret"):
            if key in qq:
                del qq[key]
                changed = True
        return changed

    def _write(self) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def apply_to_env(self) -> None:
        """把已存配置写进环境变量(覆盖,以网页配置为准)。"""
        for channel, fields in FIELD_MAP.items():
            cfg = self._data.get(channel, {})
            for key, env_name in fields.items():
                val = cfg.get(key)
                if val is None or val == "":
                    continue
                if key == "sandbox":
                    os.environ[env_name] = (
                        "1" if str(val).lower() in ("1", "true", "yes") else "0"
                    )
                else:
                    os.environ[env_name] = str(val)

    def get_masked(self) -> dict:
        """对外返回:密码类字段只回 '已配置' 标记,不回明文。"""
        out: dict = {}
        for channel, fields in FIELD_MAP.items():
            cfg = self._data.get(channel, {})
            out[channel] = {}
            for key in fields:
                val = cfg.get(key, "")
                if key in SECRET_FIELDS:
                    out[channel][key] = "******" if val else ""
                else:
                    out[channel][key] = val
        return out

    def update(self, channel: str, values: dict) -> None:
        """更新某渠道配置;空字符串的密码字段视为"不改动"(保留原值)。"""
        if channel not in FIELD_MAP:
            return
        cur = self._data.setdefault(channel, {})
        for key, env_name in FIELD_MAP[channel].items():
            if key not in values:
                continue
            new_val = values[key]
            if key in SECRET_FIELDS and (new_val == "" or new_val == "******"):
                continue  # 不覆盖已存的密钥
            cur[key] = new_val
        self._write()
        self.apply_to_env()

    def is_configured(self, channel: str) -> bool:
        cfg = self._data.get(channel, {})
        if channel == "qq":
            secret = cfg.get("app_secret") or cfg.get("secret") or cfg.get("token")
            return bool(cfg.get("app_id") and secret)
        required = {"email": "user", "wechat": "corp_id"}.get(channel)
        return bool(cfg.get(required)) if required else False
