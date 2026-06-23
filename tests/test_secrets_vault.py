"""凭据保险库回归 —— 加密往返 + 列举不泄密 + secret.list 能力不含密码。"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.secrets_vault import SecretsVault


def _fresh() -> SecretsVault:
    d = tempfile.mkdtemp()
    return SecretsVault(db_path=os.path.join(d, "vault.db"),
                        key_file=os.path.join(d, ".vault_key"))


def test_roundtrip_and_list_hides_password():
    v = _fresh()
    v.save("gmail", secret="hunter2", username="me@gmail.com", url="https://mail.google.com")
    assert v.get("gmail") == "hunter2"            # 内部解引用拿明文
    rows = v.list()
    assert rows and rows[0]["name"] == "gmail"
    assert rows[0]["username"] == "me@gmail.com"
    assert rows[0]["has_secret"] is True
    # 列举结果里**绝不**包含明文密码
    assert all("hunter2" not in str(val) for r in rows for val in r.values())
    v.close()


def test_ciphertext_not_plaintext_on_disk():
    d = tempfile.mkdtemp()
    db = os.path.join(d, "vault.db")
    v = SecretsVault(db_path=db, key_file=os.path.join(d, ".vault_key"))
    v.save("oa", secret="S3cr3t!", username="u")
    v.close()
    blob = open(db, "rb").read()
    assert b"S3cr3t!" not in blob   # 落盘是密文,磁盘上搜不到明文


def test_update_keeps_old_secret_when_blank():
    v = _fresh()
    v.save("x", secret="pw1", username="a")
    v.save("x", username="a2")     # 只更新用户名,不传密码
    assert v.get("x") == "pw1"     # 密码保留
    assert v.list()[0]["username"] == "a2"
    v.close()


def test_secret_list_capability_has_no_password():
    from capabilities.tools.secret import SecretSave, SecretList

    class Ctx:
        pass
    ctx = Ctx()
    ctx.vault = _fresh()
    asyncio.run(SecretSave().invoke(
        {"name": "svc", "secret": "topsecret", "username": "bob"}, ctx))
    r = asyncio.run(SecretList().invoke({}, ctx))
    assert r.ok and "svc" in r.output and "bob" in r.output
    assert "topsecret" not in r.output   # 能力输出绝不含密码
    ctx.vault.close()
