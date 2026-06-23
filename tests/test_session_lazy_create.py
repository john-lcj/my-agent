"""空会话不落库、首条消息才落库 —— 修"第一个对话删不掉(空会话幽灵)"。

行为:
- 仅查看历史(WS init / bind create=False):新会话不写库行,列表里看不到。
- 真有消息(消息处理 bind create=True):建库行 + 存消息,列表里可见、可删且不复活。
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.context import Context
from memory.session_store import SessionStore


def _store():
    d = tempfile.mkdtemp()
    return SessionStore(db_path=os.path.join(d, "s.db"))


def test_history_view_does_not_persist_empty_session():
    store = _store()
    ctx = Context()
    ctx.bind_session(store, "s-chat-empty", create=False)   # 仅看历史
    assert store.list_sessions() == []                       # 空会话不落库


def test_first_message_persists_session():
    store = _store()
    ctx = Context()
    ctx.bind_session(store, "s-chat-real", create=True)       # 有消息要处理
    ctx.add_user("你好")
    ids = [s["id"] for s in store.list_sessions()]
    assert "s-chat-real" in ids                               # 有内容才落库


def test_deleted_empty_session_does_not_respawn():
    """删后重连(只看历史)不应再次落库 —— 杜绝幽灵会话。"""
    store = _store()
    # 模拟:用户发过消息 -> 落库
    c1 = Context(); c1.bind_session(store, "s-chat-x", create=True); c1.add_user("hi")
    store.delete_session("s-chat-x")
    assert store.list_sessions() == []
    # 删后前端重连只 bind 看历史(create=False)-> 不应复活
    c2 = Context(); c2.bind_session(store, "s-chat-x", create=False)
    assert store.list_sessions() == []
