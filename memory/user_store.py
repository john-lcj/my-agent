"""用户存储 —— 注册/登录/套餐管理。

表结构:
  users(id, email, password_hash, plan, created_at, quota_daily)

plan: 'free' | 'pro'
quota_daily: 每日 token 上限(0 = 无限,仅 pro)
"""
from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
import time
import uuid
from typing import Optional


def _hash_password(password: str) -> str:
    """使用 PBKDF2-SHA256 哈希密码(stdlib 零依赖)。"""
    salt = os.urandom(16).hex()
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
    return f"pbkdf2:sha256:{salt}:{dk.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        _, algo, salt, dk_hex = stored.split(":", 3)
        dk = hashlib.pbkdf2_hmac(algo, password.encode(), salt.encode(), 260_000)
        return hmac.compare_digest(dk.hex(), dk_hex)
    except Exception:
        return False


class UserStore:
    FREE_QUOTA = 50_000    # 免费用户每日 token 上限
    PRO_QUOTA  = 0         # pro 用户不限(0 = 无限)

    def __init__(self, db_path: str = "logs/users.db") -> None:
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id            TEXT PRIMARY KEY,
                email         TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                plan          TEXT NOT NULL DEFAULT 'free',
                quota_daily   INTEGER NOT NULL DEFAULT 50000,
                created_at    REAL NOT NULL,
                last_login    REAL
            );
            CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

            CREATE TABLE IF NOT EXISTS redeem_codes (
                code       TEXT PRIMARY KEY,
                plan       TEXT NOT NULL DEFAULT 'pro',
                months     INTEGER NOT NULL DEFAULT 1,
                used_by    TEXT,
                used_at    REAL,
                created_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS token_usage (
                user_id  TEXT NOT NULL,
                day      TEXT NOT NULL,
                tokens   INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, day)
            );
        """)
        self._conn.commit()

    # ── 注册 / 登录 ──────────────────────────────────────────────────────────

    def register(self, email: str, password: str) -> dict:
        """注册新用户。成功返回用户 dict，邮箱已存在抛 ValueError。"""
        email = email.strip().lower()
        if not email or "@" not in email:
            raise ValueError("邮箱格式不正确")
        if len(password) < 6:
            raise ValueError("密码至少 6 位")
        uid = str(uuid.uuid4())
        ph  = _hash_password(password)
        try:
            self._conn.execute(
                "INSERT INTO users (id, email, password_hash, plan, quota_daily, created_at) "
                "VALUES (?,?,?,'free',?,?)",
                (uid, email, ph, self.FREE_QUOTA, time.time()),
            )
            self._conn.commit()
        except sqlite3.IntegrityError:
            raise ValueError("该邮箱已注册")
        return self.get_by_id(uid)

    def login(self, email: str, password: str) -> Optional[dict]:
        """验证密码。成功返回用户 dict，失败返回 None。"""
        email = email.strip().lower()
        row = self._conn.execute(
            "SELECT * FROM users WHERE email=?", (email,)
        ).fetchone()
        if not row:
            return None
        if not _verify_password(password, row["password_hash"]):
            return None
        self._conn.execute(
            "UPDATE users SET last_login=? WHERE id=?", (time.time(), row["id"])
        )
        self._conn.commit()
        return dict(row)

    def get_by_id(self, user_id: str) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT * FROM users WHERE id=?", (user_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_by_email(self, email: str) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT * FROM users WHERE email=?", (email.strip().lower(),)
        ).fetchone()
        return dict(row) if row else None

    # ── 用量追踪 ─────────────────────────────────────────────────────────────

    def _today(self) -> str:
        import datetime
        return datetime.date.today().isoformat()

    def record_tokens(self, user_id: str, tokens: int) -> None:
        day = self._today()
        self._conn.execute(
            "INSERT INTO token_usage(user_id,day,tokens) VALUES(?,?,?) "
            "ON CONFLICT(user_id,day) DO UPDATE SET tokens=tokens+excluded.tokens",
            (user_id, day, tokens),
        )
        self._conn.commit()

    def tokens_today(self, user_id: str) -> int:
        day = self._today()
        row = self._conn.execute(
            "SELECT tokens FROM token_usage WHERE user_id=? AND day=?",
            (user_id, day),
        ).fetchone()
        return row["tokens"] if row else 0

    def quota_exceeded(self, user_id: str) -> bool:
        user = self.get_by_id(user_id)
        if not user:
            return True
        quota = user["quota_daily"]
        if quota == 0:          # 0 = 无限
            return False
        return self.tokens_today(user_id) >= quota

    # ── 兑换码 ───────────────────────────────────────────────────────────────

    def create_redeem_code(self, plan: str = "pro", months: int = 1) -> str:
        code = uuid.uuid4().hex[:12].upper()
        self._conn.execute(
            "INSERT INTO redeem_codes(code,plan,months,created_at) VALUES(?,?,?,?)",
            (code, plan, months, time.time()),
        )
        self._conn.commit()
        return code

    def redeem(self, user_id: str, code: str) -> dict:
        """核销兑换码，升级套餐。成功返回新用户 dict，失败抛 ValueError。"""
        code = code.strip().upper()
        row = self._conn.execute(
            "SELECT * FROM redeem_codes WHERE code=?", (code,)
        ).fetchone()
        if not row:
            raise ValueError("兑换码不存在")
        if row["used_by"]:
            raise ValueError("兑换码已被使用")
        self._conn.execute(
            "UPDATE redeem_codes SET used_by=?, used_at=? WHERE code=?",
            (user_id, time.time(), code),
        )
        self._conn.execute(
            "UPDATE users SET plan=?, quota_daily=? WHERE id=?",
            (row["plan"], self.PRO_QUOTA, user_id),
        )
        self._conn.commit()
        return self.get_by_id(user_id)

    def upgrade(self, user_id: str, plan: str = "pro") -> dict:
        """直接升级（管理员用）。"""
        quota = self.PRO_QUOTA if plan == "pro" else self.FREE_QUOTA
        self._conn.execute(
            "UPDATE users SET plan=?, quota_daily=? WHERE id=?",
            (plan, quota, user_id),
        )
        self._conn.commit()
        return self.get_by_id(user_id)

    def close(self) -> None:
        self._conn.close()
