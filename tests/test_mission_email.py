"""测试 mission 邮件解析与恢复。"""
from __future__ import annotations

import pytest

from core.mission_email import (
    extract_email_body,
    parse_mission_id_prefix,
    resolve_mission_id,
    try_parse_mission_resume,
)
from memory.mission_store import MissionStore


def test_parse_mission_id_from_subject():
    assert parse_mission_id_prefix("[Captain Mission #abc12345] 任务卡住", "") == "abc12345"


def test_parse_mission_id_from_body():
    body = "mission id: deadbeef\n已上传扫描件"
    assert parse_mission_id_prefix("", body) == "deadbeef"


def test_try_parse_mission_resume(tmp_path):
    store = MissionStore(db_path=str(tmp_path / "m.db"))
    m = store.create(goal="测试任务")
    mid = m["id"]
    text = f"[Email subject:[Captain Mission #{mid[:8]}] 任务卡住]\n德国执照已上传"
    parsed = try_parse_mission_resume(text, store)
    assert parsed is not None
    got_mid, info = parsed
    assert got_mid == mid
    assert "德国执照" in info


def test_extract_body_strips_subject_line():
    raw = "[Email subject:hello]\nBody text内容"
    assert extract_email_body(raw) == "Body text内容"


def test_resolve_mission_id_prefix():
    store = MissionStore(db_path=":memory:")
    m = store.create(goal="x")
    assert resolve_mission_id(store, m["id"][:6]) == m["id"]
