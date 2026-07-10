"""频道配置的服务端持久化 —— 让"在网页里填的邮件配置"真正生效。

配置落到 logs/channels.json,加载时写进 os.environ,这样 EmailChannel 的
__init__(本就从 env 读)无需改动即可拿到配置。只保留邮件渠道。

字段映射(前端 key -> 环境变量):见 FIELD_MAP。密码类字段读取(对外)时打码。
"""
from __future__ import annotations

import json
import os
import tempfile

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
SECRET_FIELDS = {
    "password", "secret", "token", "aes_key", "app_secret", "bot_token",
    "signing_secret", "access_token", "api_key", "client_secret", "private_key",
}
CHANNEL_SECRET_ENV = {
    "EMAIL_PASS": ("email", "password"),
    "WECOM_SECRET": ("wecom", "secret"),
    "WECOM_TOKEN": ("wecom", "token"),
    "WECOM_AES_KEY": ("wecom", "aes_key"),
    "ONEBOT_ACCESS_TOKEN": ("qq", "access_token"),
    "QQ_APP_SECRET": ("qq", "app_secret"),
    "SLACK_BOT_TOKEN": ("slack", "bot_token"),
    "SLACK_SIGNING_SECRET": ("slack", "signing_secret"),
    "TELEGRAM_BOT_TOKEN": ("telegram", "bot_token"),
    "WECHAT_SECRET": ("wechat", "secret"),
    "WECHAT_TOKEN": ("wechat", "token"),
    "WECHAT_AES_KEY": ("wechat", "aes_key"),
}
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
    def __init__(
        self,
        path: str = "logs/channels.json",
        vault=None,
        env_path: str = "",
    ) -> None:
        self.path = path
        self.env_path = env_path
        self._vault = vault
        self._owned_vault = None
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._data: dict = self._read()
        if self._migrate_plaintext_secrets():
            self._write()
        self._migrate_env_file_secrets()
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
        parent = os.path.dirname(self.path) or "."
        fd, tmp_path = tempfile.mkstemp(prefix=".channels-", suffix=".tmp", dir=parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            try:
                os.chmod(tmp_path, 0o600)
            except OSError:
                pass
            os.replace(tmp_path, self.path)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    @staticmethod
    def _secret_account(channel: str, key: str) -> str:
        return f"channel.{channel}.{key}"

    @staticmethod
    def _secret_ref_key(key: str) -> str:
        return f"{key}_ref"

    def _get_vault(self):
        if self._vault is not None:
            return self._vault
        if self._owned_vault is not None:
            return self._owned_vault
        from memory.secrets_vault import SecretsVault

        parent = os.path.dirname(self.path) or "."
        self._owned_vault = SecretsVault(
            db_path=os.path.join(parent, "vault.db"),
            key_file=os.path.join(parent, ".vault_key"),
        )
        return self._owned_vault

    def _save_secret(self, channel: str, key: str, value: str) -> str:
        account = self._secret_account(channel, key)
        try:
            from server.keychain_store import set_secret, should_use_for_path

            if should_use_for_path(self.path) and set_secret(account, value):
                return f"keychain:{account}"
        except Exception:
            pass

        vault = self._get_vault()
        vault.save(
            name=account,
            secret=value,
            description=f"{channel} channel {key}",
            scope="channel-runtime-only",
        )
        return f"vault:{account}"

    def _load_secret(self, ref: str) -> str:
        backend, sep, account = str(ref or "").partition(":")
        if not sep or not account:
            return ""
        if backend == "keychain":
            try:
                from server.keychain_store import get_secret

                return get_secret(account)
            except Exception:
                return ""
        if backend == "vault":
            try:
                return self._get_vault().get(account) or ""
            except Exception:
                return ""
        return ""

    def _migrate_plaintext_secrets(self) -> bool:
        changed = False
        for channel, cfg in self._data.items():
            if not isinstance(cfg, dict):
                continue
            for key in list(cfg):
                if key.endswith("_ref") or key not in SECRET_FIELDS:
                    continue
                value = str(cfg.get(key) or "")
                if value and value != "******":
                    cfg[self._secret_ref_key(key)] = self._save_secret(channel, key, value)
                    changed = True
                if key in cfg:
                    cfg.pop(key, None)
                    changed = True
        return changed

    @staticmethod
    def _env_line_key(line: str) -> str:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            return ""
        key = stripped.partition("=")[0].strip()
        return key[7:].strip() if key.startswith("export ") else key

    def _migrate_env_file_secrets(self) -> None:
        if not self.env_path or not os.path.isfile(self.env_path):
            return
        try:
            with open(self.env_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except OSError:
            return

        migrated: set[str] = set()
        resolved: dict[str, str] = {}
        for line in lines:
            env_name = self._env_line_key(line)
            target = CHANNEL_SECRET_ENV.get(env_name)
            if target is None:
                continue
            value = line.partition("=")[2].strip().strip('"').strip("'")
            if not value:
                continue
            channel, key = target
            ref = self._save_secret(channel, key, value)
            cfg = self._data.setdefault(channel, {})
            cfg[self._secret_ref_key(key)] = ref
            cfg.pop(key, None)
            migrated.add(env_name)
            resolved[env_name] = value

        if not migrated:
            return
        self._write()
        parent = os.path.dirname(self.env_path) or "."
        fd, tmp_path = tempfile.mkstemp(prefix=".env-", suffix=".tmp", dir=parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                for line in lines:
                    if self._env_line_key(line) not in migrated:
                        f.write(line)
                f.flush()
                os.fsync(f.fileno())
            os.chmod(tmp_path, 0o600)
            os.replace(tmp_path, self.env_path)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        os.environ.update(resolved)

    def _secret_value(self, cfg: dict, key: str) -> str:
        return self._load_secret(str(cfg.get(self._secret_ref_key(key)) or ""))

    def _secret_configured(self, cfg: dict, key: str) -> bool:
        return bool(cfg.get(self._secret_ref_key(key)))

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
                val = self._secret_value(cfg, key) if key in SECRET_FIELDS else cfg.get(key)
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
        for env_name, (channel, key) in CHANNEL_SECRET_ENV.items():
            cfg = self._data.get(channel)
            if not isinstance(cfg, dict):
                continue
            value = self._secret_value(cfg, key)
            if value:
                os.environ[env_name] = value

    def get_masked(self) -> dict:
        """对外返回:密码类字段只回 '已配置' 标记,不回明文。"""
        out: dict = {}
        for channel, fields in FIELD_MAP.items():
            cfg = self._data.get(channel, {})
            if channel == "email":
                cfg = finalize_email_cfg(cfg)
            out[channel] = {}
            for key in fields:
                if key in SECRET_FIELDS:
                    out[channel][key] = "******" if self._secret_configured(cfg, key) else ""
                else:
                    out[channel][key] = cfg.get(key, "")
        return out

    def update(self, channel: str, values: dict) -> None:
        """更新某渠道配置;空字符串的密码字段视为"不改动"(保留原值)。"""
        if channel not in FIELD_MAP:
            return
        cur = dict(self._data.get(channel, {}))
        for key, env_name in FIELD_MAP[channel].items():
            if key not in values:
                continue
            new_val = values[key]
            if key in SECRET_FIELDS and (new_val == "" or new_val == "******"):
                continue  # 不覆盖已存的密钥
            if key in SECRET_FIELDS:
                cur[self._secret_ref_key(key)] = self._save_secret(
                    channel, key, str(new_val)
                )
                cur.pop(key, None)
            else:
                cur[key] = new_val
        if channel == "email":
            cur = finalize_email_cfg(cur)
        self._data[channel] = cur
        self._write()
        self.apply_to_env()

    def is_configured(self, channel: str) -> bool:
        cfg = self._data.get(channel, {})
        if channel == "email":
            return bool(cfg.get("user"))
        if channel == "wecom":
            return bool(
                cfg.get("corp_id")
                and self._secret_configured(cfg, "secret")
                and cfg.get("agent_id")
            )
        required = {"email": "user"}.get(channel)
        return bool(cfg.get(required)) if required else False
