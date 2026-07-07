"""频道配置的服务端持久化 —— 让"在网页里填的邮件配置"真正生效。

配置落到 logs/channels.json,加载时写进 os.environ,这样 EmailChannel 的
__init__(本就从 env 读)无需改动即可拿到配置。只保留邮件渠道。

字段映射(前端 key -> 环境变量):见 FIELD_MAP。密码类字段读取(对外)时打码。
"""
from __future__ import annotations

import json
import os

from channels.email_channel import infer_email_servers

# 前端字段 -> 环境变量名
FIELD_MAP = {
    "email": {
        "imap": "EMAIL_IMAP_HOST", "imap_port": "EMAIL_IMAP_PORT",
        "smtp": "EMAIL_SMTP_HOST", "smtp_port": "EMAIL_SMTP_PORT",
        "user": "EMAIL_USER", "password": "EMAIL_PASS",
        "allowed": "EMAIL_ALLOWED_SENDERS",
    },
    "wecom": {
        "corp_id": "WECOM_CORP_ID",
        "agent_id": "WECOM_AGENT_ID",
        "secret": "WECOM_SECRET",
        "token": "WECOM_TOKEN",
        "aes_key": "WECOM_AES_KEY",
        "allowed": "WECOM_ALLOWED_USERS",
    },
}
SECRET_FIELDS = {"password", "secret", "aes_key"}
_INVALID_HOSTS = {"", "localhost", "127.0.0.1", "::1"}


def _normalize_allowlist(raw: str, owner: str = "") -> str:
    """逗号分隔邮箱去重、小写化;始终包含账号本人(若有)。"""
    raw = (raw or "").replace("，", ",")
    addrs = {a.strip().lower() for a in (raw or "").split(",") if a.strip()}
    owner = (owner or "").strip().lower()
    if owner:
        addrs.add(owner)
    return ", ".join(sorted(addrs))


def apply_email_allow_env(cfg: dict) -> None:
    """同步入站/出站邮件白名单到环境变量。

    - EMAIL_ALLOWED_SENDERS: 只响应这些发件人的来信(UI「白名单发件人」)
    - EMAIL_ALLOWED_RECIPIENTS: Agent 主动外发/定时投递允许的收件人
    """
    allowed_raw = str(cfg.get("allowed", "") or "").strip().replace("，", ",")
    owner = str(cfg.get("user", "") or "").strip()
    if allowed_raw:
        merged = _normalize_allowlist(allowed_raw, owner)
        os.environ["EMAIL_ALLOWED_SENDERS"] = allowed_raw
        os.environ["EMAIL_ALLOWED_RECIPIENTS"] = merged
    else:
        os.environ.pop("EMAIL_ALLOWED_SENDERS", None)
        os.environ.pop("EMAIL_ALLOWED_RECIPIENTS", None)


def _clean_host(host: str) -> str:
    h = (host or "").strip()
    return "" if h.lower() in _INVALID_HOSTS else h


def finalize_email_cfg(cfg: dict) -> dict:
    """保存/加载前补全常见邮箱 IMAP/SMTP,并剔除指向本机的无效主机。"""
    out = dict(cfg or {})
    user = str(out.get("user", "")).strip()
    out["imap"] = _clean_host(str(out.get("imap", "")))
    out["smtp"] = _clean_host(str(out.get("smtp", "")))
    if not user:
        return out
    ih, sh, ip, sp = infer_email_servers(user)
    if not out.get("imap") and ih:
        out["imap"] = ih
    if not out.get("smtp") and sh:
        out["smtp"] = sh
    if not str(out.get("imap_port", "")).strip():
        out["imap_port"] = str(ip)
    if not str(out.get("smtp_port", "")).strip():
        out["smtp_port"] = str(sp)
    return out


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
            if channel == "email":
                cfg = finalize_email_cfg(cfg)
            for key, env_name in fields.items():
                if channel == "email" and key == "allowed":
                    continue
                if channel == "wecom" and key == "allowed":
                    continue
                val = cfg.get(key)
                if val is None or val == "":
                    os.environ.pop(env_name, None)
                    continue
                os.environ[env_name] = str(val)
            if channel == "email":
                apply_email_allow_env(cfg)
            if channel == "wecom":
                raw = str(cfg.get("allowed") or "").strip()
                if raw:
                    os.environ["WECOM_ALLOWED_USERS"] = raw.replace("，", ",")
                else:
                    os.environ.pop("WECOM_ALLOWED_USERS", None)

    def get_masked(self) -> dict:
        """对外返回:密码类字段只回 '已配置' 标记,不回明文。"""
        out: dict = {}
        for channel, fields in FIELD_MAP.items():
            cfg = self._data.get(channel, {})
            if channel == "email":
                cfg = finalize_email_cfg(cfg)
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
        if channel == "email":
            self._data[channel] = finalize_email_cfg(cur)
        self._write()
        self.apply_to_env()

    def is_configured(self, channel: str) -> bool:
        cfg = self._data.get(channel, {})
        if channel == "email":
            return bool(cfg.get("user"))
        if channel == "wecom":
            return bool(cfg.get("corp_id") and cfg.get("secret") and cfg.get("agent_id"))
        required = {"email": "user"}.get(channel)
        return bool(cfg.get(required)) if required else False
