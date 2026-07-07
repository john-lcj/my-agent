"""加密凭据保险库 —— 让 Captain 能"记住"登录信息并安全自动登录。

安全红线(务必守住):
  · 密码/密钥**只以密文落盘**(Fernet 对称加密),明文绝不写文件、不进日志、不进 git。
  · 加密主密钥优先放进**系统钥匙串**(keyring);拿不到钥匙串时降级到本地密钥文件
    (logs/.vault_key,权限 0600,logs/ 已 gitignore)。
  · 用户名/登录页等**非密信息**以明文存,方便 agent 引用与填表;唯独密码加密。
  · 取密码只走 get()(供 browser.fill 内部解引用),**绝不**把明文回传到模型上下文。

存储:logs/vault.db,表 secrets(name PK, username, url, note, ciphertext, updated_at)。
"""
from __future__ import annotations

import base64
import os
import sqlite3
import time
from typing import Optional

_KEYRING_SERVICE = "captain-agent-vault"
_KEYRING_USER = "fernet_key"


def _load_or_create_key(key_file: str) -> bytes:
    """取/建 Fernet 主密钥:优先系统钥匙串,降级到 0600 本地文件。"""
    from cryptography.fernet import Fernet

    # 1) 系统钥匙串
    try:
        import keyring
        existing = keyring.get_password(_KEYRING_SERVICE, _KEYRING_USER)
        if existing:
            return existing.encode()
        key = Fernet.generate_key()
        keyring.set_password(_KEYRING_SERVICE, _KEYRING_USER, key.decode())
        return key
    except Exception:
        pass  # 钥匙串不可用(无 DBus/SecretService 等)→ 降级

    # 2) 本地密钥文件(0600)
    if os.path.isfile(key_file):
        with open(key_file, "rb") as f:
            return f.read().strip()
    key = Fernet.generate_key()
    parent = os.path.dirname(key_file)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(key_file, "wb") as f:
        f.write(key)
    try:
        os.chmod(key_file, 0o600)
    except Exception:
        pass
    return key


class SecretsVault:
    def __init__(self, db_path: str = "logs/vault.db",
                 key_file: str = "logs/.vault_key") -> None:
        from cryptography.fernet import Fernet
        self.db_path = db_path
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._fernet = Fernet(_load_or_create_key(key_file))
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS secrets (
                name TEXT PRIMARY KEY,
                username TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                ciphertext BLOB NOT NULL DEFAULT '',
                updated_at REAL NOT NULL DEFAULT 0,
                description TEXT NOT NULL DEFAULT '',
                scope TEXT NOT NULL DEFAULT ''
            )
            """
        )
        # 旧库迁移：补 description / scope 列（已有列的 ALTER TABLE 会报错，静默忽略）
        for col in ("description TEXT NOT NULL DEFAULT ''",
                    "scope TEXT NOT NULL DEFAULT ''"):
            try:
                self._conn.execute(f"ALTER TABLE secrets ADD COLUMN {col}")
            except Exception:
                pass
        self._conn.commit()

    def save(self, name: str, secret: str = "", username: str = "",
             url: str = "", note: str = "",
             description: str = "", scope: str = "") -> None:
        """保存一条凭据:secret(密码/密钥)加密存,其余明文存。重名覆盖。

        description: 这个 key 的用途说明（如"Tencent Cloud main account"）
        scope:       权限范围（如"CVM 管理、COS 读写"）
        """
        name = (name or "").strip()
        if not name:
            raise ValueError("name 不能为空")
        cipher = self._fernet.encrypt((secret or "").encode()) if secret else b""
        self._conn.execute(
            "INSERT INTO secrets "
            "(name, username, url, note, ciphertext, updated_at, description, scope) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET username=excluded.username, url=excluded.url, "
            "note=excluded.note, description=excluded.description, scope=excluded.scope, "
            "ciphertext=CASE WHEN length(excluded.ciphertext)>0 THEN excluded.ciphertext ELSE secrets.ciphertext END, "
            "updated_at=excluded.updated_at",
            (name, username or "", url or "", note or "", cipher, time.time(),
             description or "", scope or ""),
        )
        self._conn.commit()

    def get(self, name: str) -> Optional[str]:
        """取明文密码 —— 仅供内部解引用(如 browser.fill),不要回传模型上下文。"""
        row = self._conn.execute(
            "SELECT ciphertext FROM secrets WHERE name = ?", ((name or "").strip(),)
        ).fetchone()
        if not row or not row["ciphertext"]:
            return None
        try:
            return self._fernet.decrypt(row["ciphertext"]).decode()
        except Exception:
            return None

    def get_username(self, name: str) -> str:
        row = self._conn.execute(
            "SELECT username FROM secrets WHERE name = ?", ((name or "").strip(),)
        ).fetchone()
        return row["username"] if row else ""

    def list(self) -> list[dict]:
        """列出凭据元信息(name/username/url/note/description/scope/updated_at)—— **不含密码**。"""
        rows = self._conn.execute(
            "SELECT name, username, url, note, description, scope, updated_at, "
            "length(ciphertext) AS has_secret "
            "FROM secrets ORDER BY updated_at DESC"
        ).fetchall()
        return [
            {"name": r["name"], "username": r["username"], "url": r["url"],
             "note": r["note"], "description": r["description"], "scope": r["scope"],
             "updated_at": r["updated_at"], "has_secret": bool(r["has_secret"])}
            for r in rows
        ]

    def delete(self, name: str) -> bool:
        cur = self._conn.execute("DELETE FROM secrets WHERE name = ?", ((name or "").strip(),))
        self._conn.commit()
        return cur.rowcount > 0

    def close(self) -> None:
        self._conn.close()
