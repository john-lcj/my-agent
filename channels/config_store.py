"""频道配置的服务端持久化 —— 让"在网页里填的邮件配置"真正生效。

配置落到 logs/channels.json,加载时写进 os.environ,这样 EmailChannel 的
__init__(本就从 env 读)无需改动即可拿到配置。只保留邮件渠道。

字段映射(前端 key -> 环境变量):见 FIELD_MAP。密码类字段读取(对外)时打码。
"""
from __future__ import annotations

import json
import os

# 前端字段 -> 环境变量名(仅邮件)
FIELD_MAP = {
    "email": {
        "imap": "EMAIL_IMAP_HOST", "imap_port": "EMAIL_IMAP_PORT",
        "smtp": "EMAIL_SMTP_HOST", "smtp_port": "EMAIL_SMTP_PORT",
        "user": "EMAIL_USER", "password": "EMAIL_PASS",
        "allowed": "EMAIL_ALLOWED_SENDERS",
    },
}
SECRET_FIELDS = {"password"}


class ChannelConfigStore:
    def __init__(self, path: str = "logs/channels.json") -> None:
        self.path = path
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._data: dict = self._read()
        self.apply_to_env()

    def _read(self) -> dict:
        if not os.path.isfile(self.path):
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f) or {}
        except Exception:
            return {}

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
        required = {"email": "user"}.get(channel)
        return bool(cfg.get(required)) if required else False
