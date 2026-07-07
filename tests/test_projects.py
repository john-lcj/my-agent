"""项目空间 + 会话归属/搜索 回归。"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.project_store import ProjectStore
from memory.session_store import SessionStore
from core.types import Message, Role


def test_project_crud():
    with tempfile.TemporaryDirectory() as d:
        ps = ProjectStore(os.path.join(d, "p.json"))
        p = ps.create("梯子搭建", instructions="只用 sing-box + Reality")
        assert p["id"].startswith("p_") and p["name"] == "梯子搭建"
        assert len(ps.list()) == 1
        ps.update(p["id"], name="VPN 项目")
        assert ps.get(p["id"])["name"] == "VPN 项目"
        # 持久化:新实例读得到
        assert ProjectStore(os.path.join(d, "p.json")).get(p["id"])["name"] == "VPN 项目"
        assert ps.delete(p["id"]) is True
        assert ps.list() == []


def test_project_context_block():
    with tempfile.TemporaryDirectory() as d:
        kf = os.path.join(d, "kb.md")
        open(kf, "w").write("项目背景:个人自用,日本机房")
        ps = ProjectStore(os.path.join(d, "p.json"))
        p = ps.create("X", instructions="先查证再下结论", knowledge=[kf])
        block = ps.context_block(p["id"])
        assert "专属指令" in block and "先查证再下结论" in block
        assert "工作区知识库" in block and "日本机房" in block


def test_session_project_and_search():
    with tempfile.TemporaryDirectory() as d:
        ss = SessionStore(db_path=os.path.join(d, "s.db"))
        ss.ensure_session("s1", title="搭梯子方案")
        ss.ensure_session("s2", title="写周报")
        ss.append("s1", Message(role=Role.USER, content="用 sing-box 搭 Reality"))
        # 归属项目 + 过滤
        ss.set_project("s1", "p_abc")
        assert ss.get_project_id("s1") == "p_abc"
        assert {x["id"] for x in ss.list_sessions(project_id="p_abc")} == {"s1"}
        # 搜索命中标题与Body text
        assert any(x["id"] == "s1" for x in ss.search_sessions("梯子"))      # 标题
        assert any(x["id"] == "s1" for x in ss.search_sessions("Reality"))   # Body text
        assert ss.search_sessions("不存在的词") == []
