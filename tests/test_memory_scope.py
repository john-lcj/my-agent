"""记忆隔离回归 —— 渠道+项目双隔离,全局('')始终可见。

验证「每个对接相互独立」:不同 scope 的记忆互不串;scope='' 的全局偏好
在任意 scope 下都能被检索到。覆盖关键词后端(SQLite)与混合层。
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.base import MemoryItem
from memory.longterm_sqlite import SQLiteMemory


def _fresh() -> SQLiteMemory:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)  # 让 SQLiteMemory 自建,确保走新 schema(含 scope 列)
    return SQLiteMemory(db_path=path)


def test_scope_isolation_keyword():
    mem = _fresh()
    mem.store(MemoryItem(kind="fact", content="项目A的部署地址是 a.example", scope="web|projA"))
    mem.store(MemoryItem(kind="fact", content="项目B的部署地址是 b.example", scope="web|projB"))

    a = [i.content for i in mem.retrieve("部署地址", k=10, scope="web|projA")]
    b = [i.content for i in mem.retrieve("部署地址", k=10, scope="web|projB")]
    assert any("a.example" in c for c in a)
    assert not any("b.example" in c for c in a)   # A 看不到 B
    assert any("b.example" in c for c in b)
    assert not any("a.example" in c for c in b)   # B 看不到 A
    mem.close()


def test_global_scope_always_visible():
    mem = _fresh()
    mem.store(MemoryItem(kind="preference", content="主人喜欢简洁的回答", scope=""))  # 全局偏好
    mem.store(MemoryItem(kind="fact", content="项目A的密钥放在 vault", scope="web|projA"))

    in_a = [i.content for i in mem.retrieve("喜欢", k=10, scope="web|projA")]
    in_b = [i.content for i in mem.retrieve("喜欢", k=10, scope="email|")]
    assert any("简洁" in c for c in in_a)  # 全局偏好在 A 可见
    assert any("简洁" in c for c in in_b)  # 全局偏好在另一对接也可见
    mem.close()


def test_channel_isolation():
    mem = _fresh()
    mem.store(MemoryItem(kind="fact", content="网页会话记下的临时事项", scope="web|"))
    mem.store(MemoryItem(kind="fact", content="邮件渠道记下的临时事项", scope="email|"))

    web = [i.content for i in mem.retrieve("临时事项", k=10, scope="web|")]
    mail = [i.content for i in mem.retrieve("临时事项", k=10, scope="email|")]
    assert any("网页" in c for c in web) and not any("邮件" in c for c in web)
    assert any("邮件" in c for c in mail) and not any("网页" in c for c in mail)
    mem.close()


def test_scope_none_returns_all():
    """scope=None(不传/旧调用)= 不隔离,取全部 —— 向后兼容。"""
    mem = _fresh()
    mem.store(MemoryItem(kind="fact", content="甲项目事项", scope="web|projA"))
    mem.store(MemoryItem(kind="fact", content="乙项目事项", scope="web|projB"))
    allc = [i.content for i in mem.retrieve("事项", k=10)]
    assert any("甲" in c for c in allc) and any("乙" in c for c in allc)
    mem.close()
