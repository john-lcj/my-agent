"""职场模板库 —— 首次种入、幂等、尊重用户删除。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.template_store import TemplateStore
from core.office_templates import BUILTIN_OFFICE_TEMPLATES


def test_seed_once_inserts_builtins(tmp_path):
    s = TemplateStore(db_path=str(tmp_path / "t.db"))
    n = s.seed_once(BUILTIN_OFFICE_TEMPLATES)
    assert n == len(BUILTIN_OFFICE_TEMPLATES) >= 6
    titles = [t["title"] for t in s.list()]
    assert "周报 → Word" in titles and "项目汇报 → PPT" in titles
    # 模板内容指向真正的文档生成器
    weekly = next(t for t in s.list() if t["id"] == "builtin-weekly-report")
    assert "docx_writer" in weekly["content"]


def test_seed_idempotent_and_respects_delete(tmp_path):
    db = str(tmp_path / "t.db")
    s = TemplateStore(db_path=db)
    s.seed_once(BUILTIN_OFFICE_TEMPLATES)
    # 用户删掉一个内置模板
    s.delete("builtin-weekly-report")
    # 再次种入:已标记种过 → 不应把删掉的又加回来
    n2 = s.seed_once(BUILTIN_OFFICE_TEMPLATES)
    assert n2 == 0
    assert all(t["id"] != "builtin-weekly-report" for t in s.list())


def test_seed_does_not_clobber_user_edit(tmp_path):
    s = TemplateStore(db_path=str(tmp_path / "t.db"))
    s.seed_once(BUILTIN_OFFICE_TEMPLATES)
    # 用户改了某模板内容
    s.save("我的周报", "自定义内容", "职场", tid="builtin-weekly-report")
    s.seed_once(BUILTIN_OFFICE_TEMPLATES)   # 再种一次不覆盖
    weekly = next(t for t in s.list() if t["id"] == "builtin-weekly-report")
    assert weekly["content"] == "自定义内容"
