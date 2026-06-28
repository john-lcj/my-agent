"""用户注册/登录/用量/兑换码单元测试。"""
from __future__ import annotations
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestUserStore:
    def setup_method(self):
        self.tmp = tempfile.TemporaryDirectory()
        from memory.user_store import UserStore
        self.us = UserStore(db_path=os.path.join(self.tmp.name, "users.db"))

    def teardown_method(self):
        self.us.close()
        self.tmp.cleanup()

    # ── 注册 ────────────────────────────────────────────────────────
    def test_register_success(self):
        u = self.us.register("alice@example.com", "pass123")
        assert u["email"] == "alice@example.com"
        assert u["plan"] == "free"
        assert u["quota_daily"] == 50_000

    def test_register_duplicate_raises(self):
        self.us.register("bob@example.com", "pass123")
        import pytest
        with pytest.raises(ValueError, match="已注册"):
            self.us.register("bob@example.com", "pass456")

    def test_register_bad_email_raises(self):
        import pytest
        with pytest.raises(ValueError):
            self.us.register("notanemail", "pass123")

    def test_register_short_password_raises(self):
        import pytest
        with pytest.raises(ValueError):
            self.us.register("x@y.com", "12")

    # ── 登录 ────────────────────────────────────────────────────────
    def test_login_success(self):
        self.us.register("carol@example.com", "secret!")
        u = self.us.login("carol@example.com", "secret!")
        assert u is not None
        assert u["email"] == "carol@example.com"

    def test_login_wrong_password(self):
        self.us.register("dave@example.com", "correct")
        assert self.us.login("dave@example.com", "wrong") is None

    def test_login_unknown_email(self):
        assert self.us.login("ghost@example.com", "x") is None

    def test_login_case_insensitive_email(self):
        self.us.register("Eve@Example.COM", "pass99")
        u = self.us.login("eve@example.com", "pass99")
        assert u is not None

    # ── 用量 ────────────────────────────────────────────────────────
    def test_token_usage_accumulates(self):
        u = self.us.register("frank@example.com", "p123456")
        self.us.record_tokens(u["id"], 1000)
        self.us.record_tokens(u["id"], 500)
        assert self.us.tokens_today(u["id"]) == 1500

    def test_quota_not_exceeded_by_default(self):
        u = self.us.register("grace@example.com", "p123456")
        assert self.us.quota_exceeded(u["id"]) is False

    def test_quota_exceeded_when_over_limit(self):
        u = self.us.register("hank@example.com", "p123456")
        self.us.record_tokens(u["id"], 60_000)
        assert self.us.quota_exceeded(u["id"]) is True

    def test_pro_quota_never_exceeded(self):
        u = self.us.register("iris@example.com", "p123456")
        self.us.upgrade(u["id"], "pro")
        self.us.record_tokens(u["id"], 999_999)
        assert self.us.quota_exceeded(u["id"]) is False

    # ── 兑换码 ──────────────────────────────────────────────────────
    def test_redeem_upgrades_plan(self):
        u = self.us.register("jack@example.com", "p123456")
        code = self.us.create_redeem_code("pro", 1)
        u2 = self.us.redeem(u["id"], code)
        assert u2["plan"] == "pro"
        assert u2["quota_daily"] == 0

    def test_redeem_code_used_twice_raises(self):
        import pytest
        u = self.us.register("karen@example.com", "p123456")
        code = self.us.create_redeem_code()
        self.us.redeem(u["id"], code)
        with pytest.raises(ValueError, match="已被使用"):
            self.us.redeem(u["id"], code)

    def test_redeem_invalid_code_raises(self):
        import pytest
        u = self.us.register("leo@example.com", "p123456")
        with pytest.raises(ValueError, match="不存在"):
            self.us.redeem(u["id"], "BADCODE")


class TestAuthModule:
    def test_create_and_decode_token(self):
        from server.auth import create_token, decode_token
        tok = create_token("uid-123", "u@x.com", "pro")
        payload = decode_token(tok)
        assert payload["sub"] == "uid-123"
        assert payload["email"] == "u@x.com"
        assert payload["plan"] == "pro"

    def test_invalid_token_raises(self):
        import pytest
        from fastapi import HTTPException
        from server.auth import decode_token
        with pytest.raises(HTTPException) as exc:
            decode_token("not.a.valid.token")
        assert exc.value.status_code == 401
