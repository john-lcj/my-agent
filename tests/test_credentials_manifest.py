"""测试凭据 Manifest：vault 存描述/权限，loop 自动注入系统消息。"""
from __future__ import annotations
import asyncio
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── vault 单元测试 ────────────────────────────────────────────────────────────

class TestSecretsVaultMeta:
    def setup_method(self):
        self.tmp = tempfile.TemporaryDirectory()
        db = os.path.join(self.tmp.name, "vault.db")
        key = os.path.join(self.tmp.name, ".vault_key")
        from memory.secrets_vault import SecretsVault
        self.vault = SecretsVault(db_path=db, key_file=key)

    def teardown_method(self):
        self.vault.close()
        self.tmp.cleanup()

    def test_save_and_list_description_scope(self):
        self.vault.save(
            name="tencent_cloud",
            secret="sk-xxx",
            description="腾讯云主账号",
            scope="CVM 管理、COS 读写",
        )
        rows = self.vault.list()
        assert len(rows) == 1
        r = rows[0]
        assert r["name"] == "tencent_cloud"
        assert r["description"] == "腾讯云主账号"
        assert r["scope"] == "CVM 管理、COS 读写"
        assert r["has_secret"] is True

    def test_save_without_meta_still_works(self):
        self.vault.save(name="plain_key", secret="abc")
        rows = self.vault.list()
        assert rows[0]["description"] == ""
        assert rows[0]["scope"] == ""

    def test_update_scope_preserves_secret(self):
        self.vault.save(name="github", secret="ghp_xxx")
        # 更新描述不传 secret，密钥应保留
        self.vault.save(name="github", description="GitHub token", scope="repo 读写")
        assert self.vault.get("github") == "ghp_xxx"
        rows = self.vault.list()
        assert rows[0]["description"] == "GitHub token"
        assert rows[0]["scope"] == "repo 读写"

    def test_old_db_migration(self):
        """旧库没有 description/scope 列，迁移后能正常读写。"""
        import sqlite3, tempfile
        tmp2 = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp2.close()
        # 建一个没有新列的旧表
        conn = sqlite3.connect(tmp2.name)
        conn.execute("""
            CREATE TABLE secrets (
                name TEXT PRIMARY KEY,
                username TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                ciphertext BLOB NOT NULL DEFAULT '',
                updated_at REAL NOT NULL DEFAULT 0
            )
        """)
        conn.execute("INSERT INTO secrets (name, username, url, note, ciphertext, updated_at) "
                     "VALUES ('old_key', '', '', '', '', 0)")
        conn.commit()
        conn.close()
        # 用新版 vault 打开，应自动迁移
        key = os.path.join(self.tmp.name, ".vault_key2")
        from memory.secrets_vault import SecretsVault
        v = SecretsVault(db_path=tmp2.name, key_file=key)
        rows = v.list()
        assert rows[0]["name"] == "old_key"
        assert rows[0]["description"] == ""
        # 能写新字段
        v.save(name="old_key", description="旧 key 补描述")
        assert v.list()[0]["description"] == "旧 key 补描述"
        v.close()
        os.unlink(tmp2.name)


# ── secret.save 工具测试 ──────────────────────────────────────────────────────

class TestSecretSaveTool:
    def setup_method(self):
        self.tmp = tempfile.TemporaryDirectory()
        db = os.path.join(self.tmp.name, "vault.db")
        key = os.path.join(self.tmp.name, ".vault_key")
        from memory.secrets_vault import SecretsVault
        from capabilities.tools.secret import SecretSave, SecretList
        self.vault = SecretsVault(db_path=db, key_file=key)
        self.save_tool = SecretSave()
        self.list_tool = SecretList()

        class _Ctx:
            pass
        self.ctx = _Ctx()
        self.ctx.vault = self.vault

    def teardown_method(self):
        self.vault.close()
        self.tmp.cleanup()

    def test_save_with_description_and_scope(self):
        result = asyncio.run(self.save_tool.invoke({
            "name": "tencent_cloud",
            "secret": "sk-abc",
            "description": "腾讯云",
            "scope": "CVM/COS",
        }, self.ctx))
        assert result.ok
        assert "腾讯云" in result.output
        assert "CVM/COS" in result.output

    def test_list_shows_description_scope(self):
        asyncio.run(self.save_tool.invoke({
            "name": "github_token",
            "secret": "ghp_xxx",
            "description": "GitHub 个人 token",
            "scope": "repo 读写、workflow",
        }, self.ctx))
        result = asyncio.run(self.list_tool.invoke({}, self.ctx))
        assert result.ok
        assert "GitHub 个人 token" in result.output
        assert "repo 读写" in result.output


# ── loop 注入测试 ─────────────────────────────────────────────────────────────

class TestCredentialsManifestInjection:
    def setup_method(self):
        self.tmp = tempfile.TemporaryDirectory()
        db = os.path.join(self.tmp.name, "vault.db")
        key = os.path.join(self.tmp.name, ".vault_key")
        from memory.secrets_vault import SecretsVault
        from core.loop import Agent
        from core.bus import EventBus
        from core.context import Context
        from core.types import Identity
        self.vault = SecretsVault(db_path=db, key_file=key)
        self.ctx = Context(identity=Identity(subject_id="u", agent_name="a", channel="web"))
        self.ctx.vault = self.vault
        self.agent = Agent(None, None, None, EventBus())  # 仅测注入，不运行 LLM

    def teardown_method(self):
        self.vault.close()
        self.tmp.cleanup()

    def test_no_injection_when_vault_empty(self):
        self.agent._inject_credentials_manifest(self.ctx)
        block = [m for m in self.ctx.messages if "[可用凭据" in m.content]
        assert block == []

    def test_no_injection_when_no_meta(self):
        self.vault.save(name="bare_key", secret="xxx")  # 无描述
        self.agent._inject_credentials_manifest(self.ctx)
        block = [m for m in self.ctx.messages if "[可用凭据" in m.content]
        assert block == []

    def test_injects_when_description_present(self):
        self.vault.save(name="tencent_cloud", secret="sk", description="腾讯云", scope="CVM")
        self.agent._inject_credentials_manifest(self.ctx)
        block = [m for m in self.ctx.messages if "[可用凭据" in m.content]
        assert len(block) == 1
        assert "tencent_cloud" in block[0].content
        assert "腾讯云" in block[0].content
        assert "CVM" in block[0].content

    def test_deduplication_on_repeat_injection(self):
        self.vault.save(name="github", secret="g", description="GitHub token", scope="repo")
        self.agent._inject_credentials_manifest(self.ctx)
        self.agent._inject_credentials_manifest(self.ctx)
        block = [m for m in self.ctx.messages if "[可用凭据" in m.content]
        assert len(block) == 1  # 不堆叠
